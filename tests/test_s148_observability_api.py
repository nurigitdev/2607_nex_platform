from __future__ import annotations

import run_s148_observability_api as smoke

from run_s148_observability_api import main, run_observability_api, summary_line


def test_s148_observability_api_smoke() -> None:
    result = run_observability_api()
    assert result["status"] == "PASS"
    assert result["external_activation"] == "EXTERNAL_NOT_ACTIVATED"
    assert result["summary"] == {
        "slo_count": 5,
        "alert_count": 2,
        "notification_count": 2,
        "audit_event_count": 2,
        "check_count": 14,
    }
    assert summary_line(result).endswith(
        "checks=14/14 activation=EXTERNAL_NOT_ACTIVATED next=1480"
    )


def test_s148_observability_api_cli_success_and_failure(monkeypatch, capsys) -> None:
    assert main(["--summary"]) == 0
    assert "s148_observability_api=pass" in capsys.readouterr().out
    assert main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_observability_api",
        lambda: {"status": "FAIL", "summary": {}, "next_slice": "blocked"},
    )
    assert main(["--summary"]) == 1
    assert "s148_observability_api=fail" in capsys.readouterr().out
