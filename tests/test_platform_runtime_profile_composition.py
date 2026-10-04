from __future__ import annotations

import run_platform_runtime_profile_composition as smoke


def test_profile_composition_evidence_passes() -> None:
    result = smoke.run_platform_runtime_profile_composition()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert len(result["profiles"]) == 5
    assert result["protected_failure_count"] == 25
    assert result["decision"]["environment_values_projected"] is False


def test_synthetic_values_and_summary() -> None:
    assert smoke._synthetic_value("NEX_OA_DATABASE_URL").startswith("postgresql://")
    assert smoke._synthetic_value("NEX_OA_BASE_URL").startswith("https://")
    assert smoke._synthetic_value("NEX_TOKEN") == "synthetic-secret-value"

    passing = smoke.run_platform_runtime_profile_composition()
    assert smoke.summary_line(passing) == (
        "platform_runtime_profile_composition=pass profiles=5/5 "
        "protected_failures=25 next=1315"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_runtime_profile_composition=fail issues=1"
    )


def test_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_runtime_profile_composition()
    monkeypatch.setattr(
        smoke, "run_platform_runtime_profile_composition", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "composition=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_runtime_profile_composition",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert smoke.main([]) == 1
