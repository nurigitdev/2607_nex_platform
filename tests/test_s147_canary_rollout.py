from __future__ import annotations

import run_s147_canary_rollout as smoke


def test_canary_rollout_passes() -> None:
    result = smoke.run_canary_rollout()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "state_count": 4,
        "promotable_count": 1,
        "blocked_count": 1,
        "check_count": 12,
    }
    assert result["next_slice"] == "1469"


def test_summary_and_main(monkeypatch, capsys) -> None:
    result = smoke.run_canary_rollout()
    assert smoke.summary_line(result) == (
        "canary_rollout=pass states=4 promotable=1 blocked=1 "
        "checks=12/12 next=1469"
    )
    monkeypatch.setattr(smoke, "run_canary_rollout", lambda: result)
    assert smoke.main(["--summary"]) == 0
    assert "next=1469" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_canary_rollout",
        lambda: {"status": "FAIL", "summary": {}, "next_slice": "blocked"},
    )
    assert smoke.main([]) == 1
