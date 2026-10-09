from __future__ import annotations

import run_s149_security_privacy as runner


def test_security_privacy_acceptance_passes() -> None:
    result = runner.run_security_privacy_acceptance()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 11,
        "check_count": 11,
        "probe_count": 12,
        "denial_count": 10,
        "privacy_count": 2,
        "violation_count": 0,
    }
    assert result["next_slice"] == "1489"


def test_runner_summary_and_main(monkeypatch, capsys) -> None:
    passing = runner.run_security_privacy_acceptance()
    assert runner.summary_line(passing) == (
        "s149_security_privacy=pass probes=12 denials=10 privacy=2 "
        "violations=0 checks=11/11 next=1489"
    )
    assert runner.summary_line({"status": "FAIL"}) == "s149_security_privacy=fail"
    monkeypatch.setattr(runner, "run_security_privacy_acceptance", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "privacy=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_security_privacy_acceptance",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1

