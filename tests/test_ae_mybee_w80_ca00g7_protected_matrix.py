from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/deployment"))

import mybee_m1_product_acceptance_support as support
import run_mybee_w80_ca00g7_protected_matrix as acceptance


def test_source_admission_freezes_six_journeys_and_exact_dependencies() -> None:
    result = acceptance.run_protected_matrix({}, execute=False)

    assert result["status"] == "SOURCE_ADMITTED"
    assert result["journey_count"] == 6
    assert result["actual_postgres_required"] is True
    assert result["actual_remote_generation_required"] is True
    assert result["actual_playwright_required"] is True
    assert result["restart_replay_required"] is True
    assert result["repository_full_gate_required"] is True
    assert result["scenario_product_residue"] == []


def test_scenario_matrix_is_tiered_but_contains_no_allocation_request() -> None:
    matrix = acceptance._scenario_matrix(acceptance.load_acceptance_baseline())

    assert [item["expected_business_stages"] for item in matrix] == [
        1,
        2,
        3,
        3,
        3,
        3,
    ]
    assert {item["outcome"] for item in matrix} == {
        "ENVELOPE_ONLY",
        "JOURNAL_SUCCESS",
        "MIDDLE_REJECTION",
        "FINAL_REJECTION",
        "ACCOUNTING_CORRECTION",
    }
    assert all("배부는 수행하지 마" in item["prompt"] for item in matrix)
    assert all("KRW" in item["prompt"] and "USD" not in item["prompt"] for item in matrix)


def test_database_gate_requires_exact_matrix_cardinality() -> None:
    database = {
        "proposal_count": 6,
        "approved_proposal_count": 4,
        "rejected_proposal_count": 2,
        "voucher_count": 4,
        "voucher_revision_count": 7,
        "journal_count": 2,
        "duplicate_pending_authority_count": 0,
        "product_checkpoint_count": 24,
    }
    browser = {
        "status": "PASS",
        "scenarios": [
            {"outcome": "ENVELOPE_ONLY", "correction_cycle": 0},
            {"outcome": "ENVELOPE_ONLY", "correction_cycle": 0},
            {
                "outcome": "JOURNAL_SUCCESS",
                "correction_cycle": 0,
                "accounting_documents": [
                    {
                        "approval_domain": "BUSINESS_FORMAL",
                        "project_code": "T001D260001",
                        "line_count": 2,
                        "balanced": True,
                        "document_identity": "T001D260001:Candidate rev. 3",
                    },
                    {
                        "approval_domain": "NSL_WRITE",
                        "project_code": "T001D260001",
                        "line_count": 2,
                        "balanced": True,
                        "document_identity": "T001D260001:Candidate rev. 3",
                    },
                ],
            },
            {"outcome": "MIDDLE_REJECTION", "correction_cycle": 0},
            {"outcome": "FINAL_REJECTION", "correction_cycle": 0},
            {
                "outcome": "ACCOUNTING_CORRECTION",
                "correction_cycle": 1,
                "accounting_documents": [
                    {
                        "approval_domain": "BUSINESS_FORMAL",
                        "project_code": "T001D260001",
                        "line_count": 2,
                        "balanced": True,
                        "document_identity": "T001D260001:Candidate rev. 2",
                    },
                    {
                        "approval_domain": "BUSINESS_FORMAL",
                        "project_code": "T001D260001",
                        "line_count": 2,
                        "balanced": True,
                        "document_identity": "T001D260001:Candidate rev. 3",
                    },
                    {
                        "approval_domain": "NSL_WRITE",
                        "project_code": "T001D260001",
                        "line_count": 2,
                        "balanced": True,
                        "document_identity": "T001D260001:Candidate rev. 3",
                    },
                ],
            },
        ],
    }
    checks = acceptance._database_checks(database, browser)
    assert all(checks.values())

    drift = dict(database, journal_count=3)
    assert acceptance._database_checks(drift, browser)[
        "two_immutable_journals"
    ] is False

    revision_drift = dict(database, voucher_revision_count=8)
    assert acceptance._database_checks(revision_drift, browser)[
        "append_only_voucher_revisions"
    ] is False


def test_browser_gate_requires_authoritative_voucher_projection_for_both_domains() -> None:
    def documents(revision: int = 3):
        identity = f"T001D260001:Candidate rev. {revision}"
        return [
            {
                "approval_domain": "BUSINESS_FORMAL",
                "project_code": "T001D260001",
                "line_count": 2,
                "balanced": True,
                "document_identity": identity,
            },
            {
                "approval_domain": "NSL_WRITE",
                "project_code": "T001D260001",
                "line_count": 2,
                "balanced": True,
                "document_identity": identity,
            },
        ]

    results = [
        {
            "scenario_id": "one-stage",
            "outcome": "ENVELOPE_ONLY",
            "business_stage_count": 1,
            "approved_envelope_present": True,
            "voucher_created": True,
            "rejected_stage": None,
            "terminal_status": "WAITING_VOUCHER_REVIEW",
            "correction_cycle": 0,
            "decision_replay_statuses": [200],
            "screen_capture_count": 1,
            "accounting_documents": [],
        },
        {
            "scenario_id": "two-stage",
            "outcome": "ENVELOPE_ONLY",
            "business_stage_count": 2,
            "approved_envelope_present": True,
            "voucher_created": True,
            "rejected_stage": None,
            "terminal_status": "WAITING_VOUCHER_REVIEW",
            "correction_cycle": 0,
            "decision_replay_statuses": [200],
            "screen_capture_count": 1,
            "accounting_documents": [],
        },
        {
            "scenario_id": "journal",
            "outcome": "JOURNAL_SUCCESS",
            "business_stage_count": 3,
            "approved_envelope_present": True,
            "voucher_created": True,
            "rejected_stage": None,
            "terminal_status": "SUCCEEDED",
            "correction_cycle": 0,
            "decision_replay_statuses": [200],
            "screen_capture_count": 1,
            "accounting_documents": documents(),
        },
        {
            "scenario_id": "middle-rejection",
            "outcome": "MIDDLE_REJECTION",
            "business_stage_count": 2,
            "approved_envelope_present": False,
            "voucher_created": False,
            "rejected_stage": 2,
            "terminal_status": "REJECTED",
            "correction_cycle": 0,
            "decision_replay_statuses": [200],
            "screen_capture_count": 1,
            "accounting_documents": [],
        },
        {
            "scenario_id": "final-rejection",
            "outcome": "FINAL_REJECTION",
            "business_stage_count": 3,
            "approved_envelope_present": False,
            "voucher_created": False,
            "rejected_stage": 3,
            "terminal_status": "REJECTED",
            "correction_cycle": 0,
            "decision_replay_statuses": [200],
            "screen_capture_count": 1,
            "accounting_documents": [],
        },
        {
            "scenario_id": "correction",
            "outcome": "ACCOUNTING_CORRECTION",
            "business_stage_count": 3,
            "approved_envelope_present": True,
            "voucher_created": True,
            "rejected_stage": None,
            "terminal_status": "SUCCEEDED",
            "correction_cycle": 1,
            "decision_replay_statuses": [200],
            "screen_capture_count": 1,
            "accounting_documents": [*documents(2)[:1], *documents(3)],
        },
    ]

    assert acceptance._browser_accounting_projection_ok({"scenarios": results}) is True
    results[2]["accounting_documents"][-1]["document_identity"] = "drift"
    assert acceptance._browser_accounting_projection_ok({"scenarios": results}) is False


def test_expected_voucher_revision_count_is_derived_from_journey_outcomes() -> None:
    browser = {
        "scenarios": [
            {"outcome": "ENVELOPE_ONLY", "correction_cycle": 0},
            {"outcome": "JOURNAL_SUCCESS", "correction_cycle": 0},
            {"outcome": "MIDDLE_REJECTION", "correction_cycle": 0},
            {"outcome": "ACCOUNTING_CORRECTION", "correction_cycle": 2},
        ]
    }

    assert acceptance._expected_voucher_revision_count(browser) == 7
    assert acceptance._expected_voucher_revision_count({}) == -1
    assert acceptance._expected_voucher_revision_count(
        {"scenarios": [{"outcome": "ACCOUNTING_CORRECTION", "correction_cycle": True}]}
    ) == -1


def test_summary_reads_nested_live_acceptance_facts() -> None:
    result = {
        "status": "PASS",
        "executed": True,
        "journey_count": 6,
        "actual_postgres": True,
        "extended_acceptance": {
            "actual_remote_generation": True,
            "actual_playwright": True,
        },
    }

    assert acceptance.summary_line(result) == (
        "mybee_w80_ca00g7_matrix=pass executed=true journeys=6 "
        "postgres=true provider=true playwright=true"
    )


def test_authority_seed_propagates_all_business_approval_position_types(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeEngine:
        def dispose(self) -> None:
            return None

    monkeypatch.setattr(support, "create_engine", lambda *_args, **_kwargs: FakeEngine())
    monkeypatch.setattr(
        support,
        "_seed_oa",
        lambda _engine, _baseline, **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(support, "_seed_eos", lambda *_args: {})

    support.seed_acceptance_authority(
        {"nex-oa": "oa", "nex-eos": "eos"},
        requester_password="requester",
        business_approver_password="business",
        accounting_approver_password="accounting",
        business_approver_position_types=("TEAM_LEAD", "GROUP_LEAD", "CEO"),
    )

    assert captured["business_approver_position_types"] == (
        "TEAM_LEAD",
        "GROUP_LEAD",
        "CEO",
    )


def test_membership_roles_follow_canonical_snapshot_shape() -> None:
    assert support._membership_roles(
        {"membership": {"roles": ["TEAM_LEAD", "GROUP_LEAD", "CEO"]}}
    ) == {"TEAM_LEAD", "GROUP_LEAD", "CEO"}
    assert support._membership_roles({"roles": ["TEAM_LEAD"]}) == set()
    assert support._membership_roles(None) == set()
