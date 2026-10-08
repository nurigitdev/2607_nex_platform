from __future__ import annotations

import run_s147_capability_calibration as smoke


def test_capability_calibration_passes() -> None:
    result = smoke.run_capability_calibration()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "capability_count": 3,
        "active_count": 3,
        "rejected_count": 1,
        "recalibration_required_count": 1,
        "check_count": 12,
    }
    assert result["next_slice"] == "1468"


def test_summary_and_main(monkeypatch, capsys) -> None:
    result = smoke.run_capability_calibration()
    assert smoke.summary_line(result) == (
        "capability_calibration=pass capabilities=3 active=3 rejected=1 "
        "recalibration=1 checks=12/12 next=1468"
    )
    monkeypatch.setattr(smoke, "run_capability_calibration", lambda: result)
    assert smoke.main(["--summary"]) == 0
    assert "next=1468" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_capability_calibration",
        lambda: {"status": "FAIL", "summary": {}, "next_slice": "blocked"},
    )
    assert smoke.main([]) == 1
