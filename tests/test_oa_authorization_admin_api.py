from __future__ import annotations

import run_oa_authorization_admin_api as smoke


def test_authorization_admin_api_evidence_passes() -> None:
    evidence = smoke.run_oa_authorization_admin_api()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_oa_authorization_admin_api()
    assert "checks=8/8" in smoke.summary_line(passing)
    assert "oa_authorization_admin_api=fail" in smoke.summary_line(
        {"status": "FAIL"}
    )
    monkeypatch.setattr(smoke, "run_oa_authorization_admin_api", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "events=4" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_oa_authorization_admin_api",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
