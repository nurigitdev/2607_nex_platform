from __future__ import annotations

import json

import run_mo_mvp_acceptance_evaluator as smoke


def test_evaluator_smoke_passes() -> None:
    result = smoke.run_mo_mvp_acceptance_evaluator()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "gate_count": 9,
        "passed_gate_count": 9,
        "blocked_gate_count": 0,
        "deterministic": True,
        "failed_check_count": 0,
    }
    assert result["next_slice"] == "1196"


def test_evaluator_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_mo_mvp_acceptance_evaluator()
    assert smoke.summary_line(passing) == (
        "mo_mvp_acceptance_evaluator=pass gates=9/9 blocked=0 "
        "deterministic=true next=1196"
    )
    assert "evaluator=fail" in smoke.summary_line({"status": "FAIL"})

    monkeypatch.setattr(smoke, "run_mo_mvp_acceptance_evaluator", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "evaluator=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        smoke, "run_mo_mvp_acceptance_evaluator", lambda: {"status": "FAIL"}
    )
    assert smoke.main([]) == 1
