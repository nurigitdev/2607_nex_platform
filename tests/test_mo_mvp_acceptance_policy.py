from __future__ import annotations

import json

import run_mo_mvp_acceptance_policy as smoke


def test_policy_smoke_passes() -> None:
    result = smoke.run_mo_mvp_acceptance_policy()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "gate_count": 9,
        "blocking_gate_count": 9,
        "max_evidence_age_hours": 24,
        "minimum_regression_tests": 9000,
        "statement_min_percent": 98.0,
        "branch_min_percent": 96.0,
        "failed_check_count": 0,
    }
    assert result["next_slice"] == "1194"


def test_policy_smoke_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_mo_mvp_acceptance_policy()
    assert smoke.summary_line(passing) == (
        "mo_mvp_acceptance_policy=pass gates=9/9 freshness=24h "
        "regression=9000 coverage=98.0/96.0 next=1194"
    )
    failing = {"status": "FAIL", "summary": {}}
    assert "policy=fail" in smoke.summary_line(failing)

    monkeypatch.setattr(smoke, "run_mo_mvp_acceptance_policy", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "policy=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        smoke, "run_mo_mvp_acceptance_policy", lambda: {"status": "FAIL"}
    )
    assert smoke.main([]) == 1
