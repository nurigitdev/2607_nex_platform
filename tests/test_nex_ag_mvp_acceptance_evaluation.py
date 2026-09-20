from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from nex_ag.mvp_acceptance import build_ag_mvp_acceptance_policy
from nex_ag.mvp_acceptance_evaluation import (
    _normalize_now,
    evaluate_ag_mvp_acceptance,
)


NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)
OBSERVED_AT = "2026-09-20T02:30:00Z"


def _passing_evidence() -> dict[str, dict[str, object]]:
    common = {"status": "PASS", "observed_at": OBSERVED_AT}
    return {
        "ag_requirement_closures": {
            **common,
            "requirement_count": 33,
            "issue_count": 0,
        },
        "contract_validation": {
            **common,
            "schema_count": 81,
            "openapi_count": 7,
            "negative_fixture_count": 95,
        },
        "unit_regression": {
            **common,
            "passed_tests": 6183,
            "failed_tests": 0,
        },
        "statement_coverage": {**common, "percent": 98.83},
        "branch_coverage": {**common, "percent": 96.42},
        "postgres_smoke": {
            **common,
            "backend": "postgresql",
            "database": "nex_ag_test",
            "zero_residue": True,
        },
        "privacy_failure_runbooks": {**common, "runbook_count": 27},
        "cx_transition_handoff": {
            **common,
            "target_service": "nex-cx",
            "manifest_status": "SEALED",
        },
    }


def test_evaluator_accepts_complete_fresh_evidence_deterministically() -> None:
    first = evaluate_ag_mvp_acceptance(_passing_evidence(), now=NOW)
    second = evaluate_ag_mvp_acceptance(_passing_evidence(), now=NOW)

    assert first == second
    assert first["status"] == "ACCEPTED"
    assert first["transition_status"] == "READY_FOR_CX"
    assert first["blockers"] == []
    assert first["summary"] == {
        "gate_count": 8,
        "passed_gate_count": 8,
        "blocked_gate_count": 0,
    }
    assert len(first["acceptance_id"]) == 64
    assert first["raw_evidence_included"] is False


@pytest.mark.parametrize(
    ("gate_id", "updates", "reason"),
    [
        (
            "ag_requirement_closures",
            {"requirement_count": 32},
            "requirement_count_incomplete",
        ),
        (
            "ag_requirement_closures",
            {"issue_count": 1},
            "closure_inventory_has_issues",
        ),
        (
            "contract_validation",
            {"schema_count": 0},
            "contract_family_empty",
        ),
        (
            "unit_regression",
            {"passed_tests": 5999},
            "regression_pass_count_below_minimum",
        ),
        (
            "unit_regression",
            {"failed_tests": 1},
            "regression_failures_present",
        ),
        (
            "statement_coverage",
            {"percent": 97.99},
            "coverage_below_threshold",
        ),
        (
            "branch_coverage",
            {"percent": 95.99},
            "coverage_below_threshold",
        ),
        (
            "postgres_smoke",
            {"backend": "sqlite"},
            "postgres_backend_not_proven",
        ),
        (
            "postgres_smoke",
            {"database": "nex_ag_dev"},
            "test_database_not_proven",
        ),
        (
            "postgres_smoke",
            {"zero_residue": False},
            "postgres_cleanup_not_proven",
        ),
        (
            "privacy_failure_runbooks",
            {"runbook_count": 26},
            "runbook_inventory_incomplete",
        ),
        (
            "cx_transition_handoff",
            {"target_service": "nex-ae-api"},
            "handoff_target_invalid",
        ),
        (
            "cx_transition_handoff",
            {"manifest_status": "DRAFT"},
            "handoff_manifest_not_sealed",
        ),
    ],
)
def test_evaluator_blocks_gate_specific_failures(
    gate_id: str, updates: dict[str, object], reason: str
) -> None:
    evidence = _passing_evidence()
    evidence[gate_id].update(updates)

    report = evaluate_ag_mvp_acceptance(evidence, now=NOW)

    assert report["status"] == "BLOCKED"
    blocker = next(item for item in report["blockers"] if item["gate_id"] == gate_id)
    assert reason in blocker["reason_codes"]


@pytest.mark.parametrize(
    ("observed_at", "reason"),
    [
        ("2026-09-18T00:00:00Z", "evidence_stale"),
        ("2026-09-20T03:06:00Z", "evidence_from_future"),
        ("not-a-time", "observed_at_invalid"),
        (None, "observed_at_invalid"),
        ("2026-09-20T02:30:00", "observed_at_invalid"),
    ],
)
def test_evaluator_blocks_invalid_evidence_time(observed_at, reason: str) -> None:
    evidence = _passing_evidence()
    evidence["contract_validation"]["observed_at"] = observed_at

    report = evaluate_ag_mvp_acceptance(evidence, now=NOW)

    blocker = next(
        item for item in report["blockers"]
        if item["gate_id"] == "contract_validation"
    )
    assert reason in blocker["reason_codes"]


def test_evaluator_blocks_missing_and_non_pass_evidence() -> None:
    missing = _passing_evidence()
    missing.pop("contract_validation")
    failed = _passing_evidence()
    failed["postgres_smoke"]["status"] = "SKIPPED"

    missing_report = evaluate_ag_mvp_acceptance(missing, now=NOW)
    failed_report = evaluate_ag_mvp_acceptance(failed, now=NOW)

    assert missing_report["blockers"][0] == {
        "gate_id": "contract_validation",
        "reason_codes": ["evidence_missing"],
    }
    postgres = next(
        item for item in failed_report["blockers"]
        if item["gate_id"] == "postgres_smoke"
    )
    assert "status_not_pass" in postgres["reason_codes"]


def test_evaluator_rejects_invalid_policy_and_naive_now() -> None:
    invalid = deepcopy(build_ag_mvp_acceptance_policy({}))
    invalid["gates"] = "invalid"

    with pytest.raises(ValueError, match="policy is invalid"):
        evaluate_ag_mvp_acceptance(_passing_evidence(), policy=invalid, now=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_ag_mvp_acceptance(
            _passing_evidence(), now=datetime(2026, 9, 20, 3, 0)
        )


def test_default_evaluation_clock_is_timezone_aware() -> None:
    assert _normalize_now(None).tzinfo is not None


def test_unknown_policy_gate_is_blocked() -> None:
    policy = deepcopy(build_ag_mvp_acceptance_policy({}))
    policy["gates"].append(
        {
            "gate_id": "unknown_gate",
            "severity": "BLOCKING",
            "required_status": "PASS",
            "skipped_allowed": False,
            "evidence_source": "test",
        }
    )
    evidence = _passing_evidence()
    evidence["unknown_gate"] = {
        "status": "PASS",
        "observed_at": OBSERVED_AT,
    }

    report = evaluate_ag_mvp_acceptance(evidence, policy=policy, now=NOW)

    assert report["blockers"][-1] == {
        "gate_id": "unknown_gate",
        "reason_codes": ["gate_evaluator_missing"],
    }


@pytest.mark.parametrize("value", [True, "99", None])
def test_non_numeric_coverage_is_blocked(value) -> None:
    evidence = _passing_evidence()
    evidence["statement_coverage"]["percent"] = value

    report = evaluate_ag_mvp_acceptance(evidence, now=NOW)

    assert report["blockers"][0]["reason_codes"] == [
        "coverage_below_threshold"
    ]
