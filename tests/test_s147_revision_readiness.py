from __future__ import annotations

import run_s147_revision_readiness as smoke


def test_revision_readiness_passes() -> None:
    result = smoke.run_revision_readiness()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "capability_count": 3,
        "ready_count": 3,
        "blocked_count": 2,
        "check_count": 12,
    }
    assert result["next_slice"] == "1467"


def test_summary_and_main(monkeypatch, capsys) -> None:
    result = smoke.run_revision_readiness()
    assert smoke.summary_line(result) == (
        "revision_readiness=pass capabilities=3 ready=3 blocked=2 "
        "checks=12/12 next=1467"
    )
    monkeypatch.setattr(smoke, "run_revision_readiness", lambda: result)
    assert smoke.main(["--summary"]) == 0
    assert "next=1467" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_revision_readiness",
        lambda: {"status": "FAIL", "summary": {}, "next_slice": "blocked"},
    )
    assert smoke.main([]) == 1
