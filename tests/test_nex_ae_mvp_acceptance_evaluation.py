from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nex_ae_api.mvp_acceptance import build_ae_mvp_acceptance_policy
from nex_ae_api.mvp_acceptance_evaluation import (
    _gate_specific_reasons,
    _normalize_now,
    _number_at_least,
    _parse_timestamp,
    _positive_number,
    evaluate_ae_mvp_acceptance,
)


NOW = datetime(2026, 9, 29, 6, 0, tzinfo=UTC)
OBSERVED_AT = "2026-09-29T05:30:00Z"


def passing_evidence() -> dict:
    common = {"status": "PASS", "observed_at": OBSERVED_AT}
    return {
        "ae_requirement_closures": {
            **common,
            "requirement_count": 9,
            "issue_count": 0,
        },
        "contract_validation": {
            **common,
            "schema_count": 108,
            "example_count": 166,
            "negative_fixture_count": 129,
            "openapi_count": 7,
        },
        "unit_regression": {
            **common,
            "passed_tests": 8750,
            "failed_tests": 0,
        },
        "statement_coverage": {**common, "percent": 98.81},
        "branch_coverage": {**common, "percent": 96.85},
        "postgres_smoke": {
            **common,
            "backend": "postgresql",
            "databases": ["nex_ae_test", "nex_cx_test"],
            "zero_residue": True,
        },
        "live_grounded_generation": {
            **common,
            "provider_models": {
                "embedding": "Qwen3-Embedding-4B",
                "reranking": "Qwen3-Reranker-4B",
                "generation": "Qwen3.5-4B",
            },
            "failed_calls": 0,
            "browser_engine": "chromium",
            "display_state": "VERIFIED_RESPONSE",
            "server_secret_header": False,
        },
        "privacy_failure_runbooks": {**common, "runbook_count": 4},
        "operations_handoff": {
            **common,
            "target_service": "nex-ag",
            "manifest_status": "SEALED",
        },
    }


def test_passing_evidence_is_accepted_and_deterministic() -> None:
    first = evaluate_ae_mvp_acceptance(passing_evidence(), now=NOW)
    second = evaluate_ae_mvp_acceptance(passing_evidence(), now=NOW)

    assert first == second
    assert first["status"] == "ACCEPTED"
    assert first["operations_status"] == "READY_FOR_OPERATIONS"
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
        ("ae_requirement_closures", {"requirement_count": 8}, "requirement_count_incomplete"),
        ("ae_requirement_closures", {"issue_count": 1}, "closure_inventory_has_issues"),
        ("contract_validation", {"schema_count": 0}, "schema_count_empty"),
        ("contract_validation", {"example_count": False}, "example_count_empty"),
        ("unit_regression", {"passed_tests": 8499}, "regression_pass_count_below_minimum"),
        ("unit_regression", {"failed_tests": 1}, "regression_failures_present"),
        ("statement_coverage", {"percent": 97.99}, "coverage_below_threshold"),
        ("branch_coverage", {"percent": 95.99}, "coverage_below_threshold"),
        ("postgres_smoke", {"backend": "sqlite"}, "postgres_backend_not_proven"),
        ("postgres_smoke", {"databases": ["nex_ae_test"]}, "test_databases_not_proven"),
        ("postgres_smoke", {"zero_residue": False}, "postgres_cleanup_not_proven"),
        ("live_grounded_generation", {"provider_models": {}}, "live_provider_models_not_proven"),
        ("live_grounded_generation", {"failed_calls": 1}, "live_provider_failures_present"),
        ("live_grounded_generation", {"browser_engine": "unknown"}, "browser_engine_not_proven"),
        ("live_grounded_generation", {"display_state": "RUNNING"}, "verified_response_not_proven"),
        ("live_grounded_generation", {"server_secret_header": True}, "browser_secret_boundary_not_proven"),
        ("privacy_failure_runbooks", {"runbook_count": 3}, "runbook_inventory_incomplete"),
        ("operations_handoff", {"target_service": "nex-cx"}, "operations_target_invalid"),
        ("operations_handoff", {"manifest_status": "DRAFT"}, "operations_manifest_not_sealed"),
    ],
)
def test_gate_specific_failures_block_acceptance(
    gate_id: str, updates: dict, reason: str
) -> None:
    evidence = passing_evidence()
    evidence[gate_id].update(updates)

    report = evaluate_ae_mvp_acceptance(evidence, now=NOW)

    assert report["status"] == "BLOCKED"
    blocker = next(item for item in report["blockers"] if item["gate_id"] == gate_id)
    assert reason in blocker["reason_codes"]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda evidence: evidence.pop("postgres_smoke"), "evidence_missing"),
        (lambda evidence: evidence["postgres_smoke"].update(status="SKIPPED"), "status_not_pass"),
        (lambda evidence: evidence["postgres_smoke"].update(observed_at="bad"), "observed_at_invalid"),
        (lambda evidence: evidence["postgres_smoke"].update(observed_at="2026-09-30T06:00:00Z"), "evidence_from_future"),
        (lambda evidence: evidence["postgres_smoke"].update(observed_at="2026-09-27T06:00:00Z"), "evidence_stale"),
    ],
)
def test_missing_skipped_and_unfresh_evidence_blocks(mutation, reason: str) -> None:
    evidence = passing_evidence()
    mutation(evidence)

    report = evaluate_ae_mvp_acceptance(evidence, now=NOW)

    blocker = next(
        item for item in report["blockers"] if item["gate_id"] == "postgres_smoke"
    )
    assert reason in blocker["reason_codes"]


def test_invalid_policy_and_naive_clock_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_ae_mvp_acceptance(passing_evidence(), now=datetime(2026, 9, 29))

    with pytest.raises(ValueError, match="policy is invalid"):
        evaluate_ae_mvp_acceptance(
            passing_evidence(), policy={"gates": [], "evidence": {}}, now=NOW
        )

    with pytest.raises(ValueError, match="policy is invalid"):
        evaluate_ae_mvp_acceptance(
            passing_evidence(), policy={"gates": "bad", "evidence": {"max_age_hours": 1}}, now=NOW
        )


def test_helpers_cover_unknown_gate_and_value_types() -> None:
    assert _gate_specific_reasons("unknown", {}, {}) == ["gate_evaluator_missing"]
    assert _normalize_now(None).tzinfo is UTC
    assert _normalize_now(NOW) == NOW
    assert _parse_timestamp(None) is None
    assert _parse_timestamp("2026-09-29T05:30:00") is None
    assert _parse_timestamp(OBSERVED_AT) == datetime(2026, 9, 29, 5, 30, tzinfo=UTC)
    assert _positive_number(1) is True
    assert _positive_number(True) is False
    assert _number_at_least(2, 1) is True
    assert _number_at_least(True, 1) is False
    assert _number_at_least(2, "1") is False


def test_custom_policy_threshold_is_honored() -> None:
    policy = build_ae_mvp_acceptance_policy(
        {"NEX_AE_MVP_REQUIRED_REGRESSION_TESTS": "9000"}
    )
    report = evaluate_ae_mvp_acceptance(
        passing_evidence(), policy=policy, now=NOW
    )

    assert report["status"] == "BLOCKED"
    assert report["summary"]["blocked_gate_count"] == 1
