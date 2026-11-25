from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/deployment"))

import mybee_m1_product_acceptance_support as support
import run_mybee_w80_ca00f5_split_live_journeys as acceptance


def test_source_admission_requires_both_independent_product_capabilities():
    result = acceptance.run_split_live_journeys({}, execute=False)
    assert result["status"] == "SOURCE_ADMITTED"
    assert result["active_capabilities"] == [
        "FINANCE.COST_ALLOCATION.RUN",
        "FINANCE.VOUCHER.APPROVE_AND_POST",
    ]
    assert result["journal_and_allocation_are_independent"] is True
    assert result["scenario_product_residue"] == []


def test_split_prompts_keep_journal_and_allocation_responsibilities_separate():
    baseline = support.load_acceptance_baseline()
    journal = support.build_journal_prompt(baseline, transaction_index=0)
    allocation = support.build_accounting_allocation_prompt(
        baseline,
        company_id=baseline["company"]["company_id"],
        journal_id="11111111-1111-4111-8111-111111111111",
        source_record_line_ref="expense-line-1",
    )
    assert "배부를 수행하지 마" in journal
    assert "전표" in journal
    assert "새 전표를 생성하지 말고" in allocation
    assert "40.000000000000%" in allocation
    assert "60.000000000000%" in allocation
    assert "finance:allocation:execute" in support._OA_SCOPES["business_approver"]
    assert "finance:allocation:execute" not in support._OA_SCOPES["requester"]


def test_live_checks_require_one_journal_then_one_conserved_allocation():
    baseline = support.load_acceptance_baseline()
    database = {
        "execution_count": 2,
        "agent_result_count": 2,
        "acknowledged_delivery_count": 2,
        "approval_decision_count": 4,
        "voucher_candidate_count": 1,
        "journal_count": 1,
        "allocation_batch_count": 1,
        "allocation_line_count": 2,
        "pnl_projection_count": 2,
        "first_batch_allocated_total": "13502000.0000",
        "first_batch_unallocated_total": "0.0000",
        "first_batch_project_amounts": ["5400800.0000", "8101200.0000"],
    }
    checks = acceptance._live_checks(
        database=database,
        before_allocation={
            "journal_count": 1,
            "allocation_batch_count": 0,
            "pnl_projection_count": 0,
        },
        baseline=baseline,
    )
    assert all(checks.values())
    database["allocation_batch_count"] = 2
    assert not all(
        acceptance._live_checks(
            database=database,
            before_allocation={
                "journal_count": 1,
                "allocation_batch_count": 0,
                "pnl_projection_count": 0,
            },
            baseline=baseline,
        ).values()
    )


def test_browser_invocation_rejects_invalid_output(monkeypatch):
    monkeypatch.setattr(
        acceptance.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Completed", (), {"stdout": "not-json\n", "returncode": 1}
        )(),
    )
    with pytest.raises(acceptance.SplitLiveJourneyError):
        acceptance._invoke_playwright({}, [])


def test_public_browser_evidence_removes_runtime_payload():
    value = {
        "journal": {"status": "PASS", "runtime": {"secret": "raw"}},
        "allocation": {"status": "PASS", "checks": {"ok": True}},
    }
    assert acceptance._public_browser(value) == {
        "journal": {"status": "PASS"},
        "allocation": {"status": "PASS", "checks": {"ok": True}},
    }
    assert "raw" not in json.dumps(acceptance._public_browser(value))
