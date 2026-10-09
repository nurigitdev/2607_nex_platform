from __future__ import annotations

import run_s149_workload_profile as runner


def test_workload_profile_acceptance_passes() -> None:
    result = runner.run_workload_profile_acceptance()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 8,
        "check_count": 8,
        "profile_count": 3,
        "operation_count": 7,
    }
    assert result["next_slice"] == "1485"


def test_runner_summary_and_main(monkeypatch, capsys) -> None:
    passing = runner.run_workload_profile_acceptance()
    assert runner.summary_line(passing) == (
        "s149_workload_profile=pass profiles=3 operations=7 checks=8/8 next=1485"
    )
    assert runner.summary_line({"status": "FAIL"}) == "s149_workload_profile=fail"

    monkeypatch.setattr(runner, "run_workload_profile_acceptance", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "profile=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_workload_profile_acceptance",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1

