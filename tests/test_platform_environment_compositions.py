from __future__ import annotations

import run_platform_environment_compositions as smoke


def test_environment_composition_evidence_passes() -> None:
    result = smoke.run_platform_environment_compositions()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "environment_class_count": 4,
        "profile_count": 5,
        "limited_profile_count": 2,
        "blocked_profile_count": 3,
        "immutable_profile_count": 3,
    }
    assert result["decision"]["production_deployment_approved"] is False


def test_synthetic_environment_contains_names_but_runner_projects_no_values() -> None:
    local = smoke._synthetic_environment("local_mock")
    protected = smoke._synthetic_environment("production")

    assert local == {}
    assert len(protected) == 31
    assert protected["NEX_OA_DATABASE_URL"].startswith("postgresql://")
    assert protected["NEX_OA_BASE_URL"].startswith("https://")
    assert protected["NEX_OA_RUNTIME_IMAGE"].startswith("registry.example/")


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_environment_compositions()
    assert smoke.summary_line(passing) == (
        "platform_environment_compositions=pass classes=4 profiles=5 "
        "limited=2 blocked=3 immutable=3 next=1418"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_environment_compositions=fail issues=1"
    )

    monkeypatch.setattr(smoke, "run_platform_environment_compositions", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "compositions=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_environment_compositions",
        lambda: (_ for _ in ()).throw(ValueError("bad composition")),
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
