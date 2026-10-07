from __future__ import annotations

import run_platform_packaged_lifecycle as smoke


def test_packaged_lifecycle_evidence_passes() -> None:
    result = smoke.run_platform_packaged_lifecycle()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "profile_count": 5,
        "process_step_count": 65,
        "migration_step_count": 20,
        "artifact_set_size": 6,
        "blocked_profile_count": 3,
    }
    assert result["decision"]["production_contact_required"] is False


def test_synthetic_environment_uses_unique_runtime_endpoints() -> None:
    environment = smoke._synthetic_environment("production")
    endpoints = {
        value
        for name, value in environment.items()
        if name in smoke._ENDPOINT_PORTS
    }

    assert len(endpoints) == 6
    assert len(environment) == 31


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_packaged_lifecycle()
    assert smoke.summary_line(passing) == (
        "platform_packaged_lifecycle=pass profiles=5 processes=65 "
        "migrations=20 artifacts=6 blocked=3 next=1419"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_packaged_lifecycle=fail issues=1"
    )

    monkeypatch.setattr(smoke, "run_platform_packaged_lifecycle", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "lifecycle=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_packaged_lifecycle",
        lambda: (_ for _ in ()).throw(ValueError("bad lifecycle")),
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
