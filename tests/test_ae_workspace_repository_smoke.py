from __future__ import annotations

import json

import run_ae_workspace_repository_smoke as smoke


def test_workspace_repository_smoke_passes() -> None:
    result = smoke.run_workspace_repository_smoke()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["workspace_count"] == 1
    assert result["activity_count"] == 2
    assert result["postgres_required"] is False


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_workspace_repository_smoke()
    assert smoke.summary_line(passing) == (
        "ae_workspace_repository=pass checks=8/8 workspaces=1 activities=2"
    )

    monkeypatch.setattr(smoke, "run_workspace_repository_smoke", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "checks=8/8" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_workspace_repository_smoke",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert smoke.main([]) == 1
