from __future__ import annotations

import run_oa_subject_lifecycle_api as smoke


def test_subject_lifecycle_api_evidence_passes() -> None:
    result = smoke.run_oa_subject_lifecycle_api()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_oa_subject_lifecycle_api()
    assert "api=pass" in smoke.summary_line(passing)
    assert "api=fail" in smoke.summary_line({"status": "FAIL"})
    monkeypatch.setattr(smoke, "run_oa_subject_lifecycle_api", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "api=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke, "run_oa_subject_lifecycle_api", lambda: {"status": "FAIL"}
    )
    assert smoke.main([]) == 1
