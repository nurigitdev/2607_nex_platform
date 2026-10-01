from __future__ import annotations

import run_oa_subject_lifecycle_domain as smoke


def test_subject_lifecycle_domain_evidence_passes() -> None:
    result = smoke.run_oa_subject_lifecycle_domain()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["sample"]["disable"]["next_revision"] == 4


def test_error_helper_and_summary_cover_success_and_failure() -> None:
    assert smoke._error_code(lambda: None) is None
    assert "domain=pass" in smoke.summary_line({"status": "PASS"})
    assert "domain=fail" in smoke.summary_line({"status": "FAIL"})


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = smoke.run_oa_subject_lifecycle_domain()
    monkeypatch.setattr(smoke, "run_oa_subject_lifecycle_domain", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "domain=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_oa_subject_lifecycle_domain",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
