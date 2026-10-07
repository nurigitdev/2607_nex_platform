from __future__ import annotations

import run_platform_production_secret_rotation as smoke


def test_repository_rotation_evidence_passes() -> None:
    result = smoke.run_platform_production_secret_rotation()
    assert result["status"] == "PASS"
    assert all(result["state_checks"].values())
    assert result["summary"] == {
        "owner_count": 5,
        "phase_count": 4,
        "rollback_phase_count": 3,
        "verified_owner_count": 5,
    }
    assert result["decision"]["previous_generation_retired"] is False
    assert result["decision"]["next_slice"] == "1428"


def test_summary_main_and_failure_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_production_secret_rotation()
    assert smoke.summary_line(passing) == (
        "platform_production_secret_rotation=pass owners=5 phases=4 "
        "rollback=3 verified=5 next=1428"
    )
    assert smoke.summary_line({"status": "FAIL"}) == (
        "platform_production_secret_rotation=fail"
    )
    monkeypatch.setattr(smoke, "run_platform_production_secret_rotation", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "rotation=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_platform_production_secret_rotation",
        lambda: (_ for _ in ()).throw(ValueError("bad rotation")),
    )
    assert smoke.main([]) == 1


def test_smoke_detects_non_rollback_failure(monkeypatch) -> None:
    real_evaluate = smoke.evaluate_secret_rotation

    def permissive(plan, observations):
        result = real_evaluate(plan, observations)
        if result.status == "ROLLBACK_REQUIRED":
            return type(result)("VERIFIED", (), (), (), True, True)
        return result

    monkeypatch.setattr(smoke, "evaluate_secret_rotation", permissive)
    result = smoke.run_platform_production_secret_rotation()
    assert result["status"] == "FAIL"
    assert result["decision"]["next_slice"] == "blocked"
