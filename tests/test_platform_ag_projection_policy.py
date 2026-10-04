from __future__ import annotations

import run_platform_ag_projection_policy as smoke


def test_ag_projection_policy_evidence_passes() -> None:
    result = smoke.run_platform_ag_projection_policy()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"]["protected_cross_service_database_reads_allowed"] is False


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_ag_projection_policy()
    assert smoke.summary_line(passing) == (
        "platform_ag_projection_policy=pass protected=api legacy_adapters=4 next=1319"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_ag_projection_policy=fail issues=1"
    )

    monkeypatch.setattr(smoke, "run_platform_ag_projection_policy", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "policy=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_ag_projection_policy",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert smoke.main([]) == 1
