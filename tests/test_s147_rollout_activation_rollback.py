from __future__ import annotations

import run_s147_rollout_activation_rollback as smoke


def test_rollout_activation_rollback_smoke_passes() -> None:
    result = smoke.run_rollout_activation_rollback()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "binding_count": 3,
        "active_count": 1,
        "released_count": 1,
        "check_count": 12,
    }
    assert result["next_slice"] == "1470"


def test_summary_and_main(monkeypatch, capsys) -> None:
    result = smoke.run_rollout_activation_rollback()
    assert smoke.summary_line(result) == (
        "rollout_activation_rollback=pass bindings=3 active=1 "
        "released=1 checks=12/12 next=1470"
    )
    monkeypatch.setattr(smoke, "run_rollout_activation_rollback", lambda: result)
    assert smoke.main(["--summary"]) == 0
    assert "next=1470" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_rollout_activation_rollback",
        lambda: {"status": "FAIL", "summary": {}, "next_slice": "blocked"},
    )
    assert smoke.main([]) == 1
