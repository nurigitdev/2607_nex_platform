from __future__ import annotations

import run_s149_soak_stability as runner


def test_soak_stability_acceptance_passes() -> None:
    result = runner.run_soak_stability_acceptance()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 10,
        "check_count": 10,
        "window_count": 6,
        "duration_seconds": 1_800.0,
        "request_count": 7_200,
    }
    assert result["next_slice"] == "1487"


def test_runner_summary_and_main(monkeypatch, capsys) -> None:
    passing = runner.run_soak_stability_acceptance()
    assert runner.summary_line(passing) == (
        "s149_soak_stability=pass windows=6 duration=1800s requests=7200 "
        "checks=10/10 next=1487"
    )
    assert runner.summary_line({"status": "FAIL"}) == "s149_soak_stability=fail"
    monkeypatch.setattr(runner, "run_soak_stability_acceptance", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "stability=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_soak_stability_acceptance",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1

