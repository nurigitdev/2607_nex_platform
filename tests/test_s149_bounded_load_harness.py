from __future__ import annotations

import run_s149_bounded_load_harness as runner


def test_bounded_load_harness_acceptance_passes() -> None:
    result = runner.run_bounded_load_harness_acceptance()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"]["request_count"] == 70
    assert result["summary"]["operation_count"] == 7
    assert result["summary"]["passed_check_count"] == 9
    assert result["next_slice"] == "1486"


def test_runner_summary_and_main(monkeypatch, capsys) -> None:
    passing = runner.run_bounded_load_harness_acceptance()
    assert "requests=70" in runner.summary_line(passing)
    assert "checks=9/9" in runner.summary_line(passing)
    assert runner.summary_line({"status": "FAIL"}) == "s149_bounded_load_harness=fail"

    monkeypatch.setattr(runner, "run_bounded_load_harness_acceptance", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "harness=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_bounded_load_harness_acceptance",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1

