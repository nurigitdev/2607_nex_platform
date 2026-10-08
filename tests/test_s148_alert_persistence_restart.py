from __future__ import annotations

import run_s148_alert_persistence_restart as smoke


def test_alert_persistence_restart_smoke_passes() -> None:
    result = smoke.run_alert_persistence_restart()
    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "alert_count": 1,
        "notification_count": 2,
        "attempt_count": 3,
        "recovered_lease_count": 1,
        "cleanup_residue": 0,
        "check_count": 14,
    }
    assert result["next_slice"] == "1478"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_alert_persistence_restart()
    assert smoke.summary_line(passing) == (
        "s148_alert_persistence_restart=pass alerts=1 notifications=2 attempts=3 "
        "recovered=1 cleanup=0 checks=14/14 next=1478"
    )
    failed = {"status": "FAIL", "summary": {}, "next_slice": "blocked"}
    assert smoke.summary_line(failed) == (
        "s148_alert_persistence_restart=fail alerts=0 notifications=0 attempts=0 "
        "recovered=0 cleanup=-1 checks=0/14 next=blocked"
    )
    monkeypatch.setattr(smoke, "run_alert_persistence_restart", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "restart=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(smoke, "run_alert_persistence_restart", lambda: failed)
    assert smoke.main([]) == 1
