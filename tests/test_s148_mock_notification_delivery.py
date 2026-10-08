from __future__ import annotations

import run_s148_mock_notification_delivery as smoke

from run_s148_mock_notification_delivery import (
    main,
    run_mock_notification_delivery,
    summary_line,
)


def test_s148_mock_notification_delivery_smoke() -> None:
    result = run_mock_notification_delivery()
    assert result["status"] == "PASS"
    assert result["external_activation"] == "EXTERNAL_NOT_ACTIVATED"
    assert result["summary"] == {
        "notification_count": 5,
        "attempt_count": 6,
        "mock_accepted_count": 2,
        "local_delivered_count": 3,
        "check_count": 15,
    }
    assert summary_line(result).endswith(
        "checks=15/15 activation=EXTERNAL_NOT_ACTIVATED next=1479"
    )


def test_mock_notification_delivery_cli_outputs_summary_and_json(capsys) -> None:
    assert main(["--summary"]) == 0
    assert "s148_mock_notification_delivery=pass" in capsys.readouterr().out
    assert main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out


def test_mock_notification_delivery_cli_returns_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        smoke,
        "run_mock_notification_delivery",
        lambda: {"status": "FAIL", "summary": {}, "next_slice": "blocked"},
    )
    assert main(["--summary"]) == 1
    assert "s148_mock_notification_delivery=fail" in capsys.readouterr().out
