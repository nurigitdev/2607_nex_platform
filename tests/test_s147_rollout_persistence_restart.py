from __future__ import annotations

import run_s147_rollout_persistence_restart as smoke


def test_rollout_persistence_restart_smoke_passes() -> None:
    result = smoke.run_rollout_persistence_restart()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "recovered_revision": 2,
        "event_count": 2,
        "api_request_count": 3,
        "cleanup_residue": 0,
        "check_count": 13,
    }
    assert result["next_slice"] == "1471"


def test_summary_and_main(monkeypatch, capsys) -> None:
    result = smoke.run_rollout_persistence_restart()
    assert smoke.summary_line(result) == (
        "rollout_persistence_restart=pass revision=2 events=2 api=3 "
        "cleanup=0 checks=13/13 next=1471"
    )
    monkeypatch.setattr(smoke, "run_rollout_persistence_restart", lambda: result)
    assert smoke.main(["--summary"]) == 0
    assert "next=1471" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_rollout_persistence_restart",
        lambda: {"status": "FAIL", "summary": {}, "next_slice": "blocked"},
    )
    assert smoke.main([]) == 1
