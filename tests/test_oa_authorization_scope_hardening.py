from __future__ import annotations

import run_oa_authorization_scope_hardening as smoke


def test_authorization_scope_hardening_evidence_passes() -> None:
    evidence = smoke.run_oa_authorization_scope_hardening()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_oa_authorization_scope_hardening()
    assert "checks=11/11" in smoke.summary_line(passing)
    assert "scopes=3" in smoke.summary_line(passing)
    assert "oa_authorization_scope_hardening=fail" in smoke.summary_line(
        {"status": "FAIL"}
    )
    monkeypatch.setattr(smoke, "run_oa_authorization_scope_hardening", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "checks=11/11" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_oa_authorization_scope_hardening",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
