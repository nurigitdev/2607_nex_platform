from __future__ import annotations

import run_s148_signal_correlation as smoke


def test_signal_correlation_smoke_passes() -> None:
    result = smoke.run_signal_correlation()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"]["signal_count"] == 5
    assert result["next_slice"] == "1475"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_signal_correlation()
    assert smoke.summary_line(passing) == (
        "s148_signal_correlation=pass signals=5 groups=1 kinds=4 checks=8/8 next=1475"
    )
    failed = {"status": "FAIL", "checks": {}, "summary": {}, "next_slice": "blocked"}
    assert smoke.summary_line(failed) == (
        "s148_signal_correlation=fail signals=0 groups=0 kinds=0 checks=0/8 next=blocked"
    )
    monkeypatch.setattr(smoke, "run_signal_correlation", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "correlation=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(smoke, "run_signal_correlation", lambda: failed)
    assert smoke.main([]) == 1
