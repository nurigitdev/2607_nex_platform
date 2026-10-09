from __future__ import annotations

import run_s149_rollback_rehearsal as runner


def test_rollback_rehearsal_acceptance_passes() -> None:
    result = runner.run_rollback_rehearsal_acceptance()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 10,
        "check_count": 10,
        "component_count": 6,
        "verified_count": 6,
        "recovery_ms": 120_000,
        "residue_count": 0,
    }
    assert result["next_slice"] == "1490"


def test_runner_summary_and_main(monkeypatch, capsys) -> None:
    passing = runner.run_rollback_rehearsal_acceptance()
    assert runner.summary_line(passing) == (
        "s149_rollback_rehearsal=pass components=6 verified=6 recovery=120000ms "
        "residue=0 checks=10/10 next=1490"
    )
    assert runner.summary_line({"status": "FAIL"}) == "s149_rollback_rehearsal=fail"
    monkeypatch.setattr(runner, "run_rollback_rehearsal_acceptance", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "rehearsal=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_rollback_rehearsal_acceptance",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1

