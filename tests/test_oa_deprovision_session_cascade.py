from __future__ import annotations

import run_oa_deprovision_session_cascade as smoke


def test_deprovision_session_cascade_evidence_passes() -> None:
    result = smoke.run_oa_deprovision_session_cascade()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["revoked_session_count"] == 1


def test_session_builder_and_summary_paths() -> None:
    assert smoke._session("employee", status="ACTIVE")["subject_ref"]["id"] == "employee"
    assert "cascade=pass" in smoke.summary_line(
        {"status": "PASS", "revoked_session_count": 1}
    )
    assert "cascade=fail" in smoke.summary_line({"status": "FAIL"})


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = smoke.run_oa_deprovision_session_cascade()
    monkeypatch.setattr(smoke, "run_oa_deprovision_session_cascade", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "cascade=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke, "run_oa_deprovision_session_cascade", lambda: {"status": "FAIL"}
    )
    assert smoke.main([]) == 1
