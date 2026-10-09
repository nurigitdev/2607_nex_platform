from __future__ import annotations

import run_s149_fault_recovery as runner


def test_fault_recovery_acceptance_passes() -> None:
    result = runner.run_fault_recovery_acceptance()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 12,
        "check_count": 12,
        "scenario_count": 8,
        "fault_class_count": 5,
        "recovered_count": 8,
        "residue_count": 0,
    }
    assert result["next_slice"] == "1488"


def test_runner_summary_and_main(monkeypatch, capsys) -> None:
    passing = runner.run_fault_recovery_acceptance()
    assert runner.summary_line(passing) == (
        "s149_fault_recovery=pass scenarios=8 classes=5 recovered=8 residue=0 "
        "checks=12/12 next=1488"
    )
    assert runner.summary_line({"status": "FAIL"}) == "s149_fault_recovery=fail"
    monkeypatch.setattr(runner, "run_fault_recovery_acceptance", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "recovery=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_fault_recovery_acceptance",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1

