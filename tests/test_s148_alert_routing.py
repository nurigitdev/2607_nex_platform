from __future__ import annotations

import run_s148_alert_routing as smoke


def test_alert_routing_smoke_passes() -> None:
    result = smoke.run_alert_routing()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "decision_count": 3,
        "intent_count": 4,
        "blocked_count": 1,
        "external_activated_count": 1,
    }
    assert result["next_slice"] == "1477"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_alert_routing()
    assert smoke.summary_line(passing) == (
        "s148_alert_routing=pass decisions=3 intents=4 blocked=1 checks=8/8 next=1477"
    )
    failed = {"status": "FAIL", "checks": {}, "summary": {}, "next_slice": "blocked"}
    assert smoke.summary_line(failed) == (
        "s148_alert_routing=fail decisions=0 intents=0 blocked=0 checks=0/8 next=blocked"
    )
    monkeypatch.setattr(smoke, "run_alert_routing", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "routing=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(smoke, "run_alert_routing", lambda: failed)
    assert smoke.main([]) == 1
