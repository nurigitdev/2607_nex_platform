from __future__ import annotations

import json

import run_ae_durable_workspace_chat_orchestration as smoke


def test_durable_workspace_chat_orchestration_smoke_passes() -> None:
    result = smoke.run_durable_workspace_chat_orchestration_smoke()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["interaction_count"] == 1
    assert result["activity_count"] == 3
    assert result["provider_call_count"] == 1
    assert result["postgres_required"] is False


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_durable_workspace_chat_orchestration_smoke()
    assert smoke.summary_line(passing) == (
        "ae_durable_workspace_chat_orchestration=pass checks=12/12 "
        "interactions=1 activities=3 provider_calls=1"
    )

    monkeypatch.setattr(
        smoke,
        "run_durable_workspace_chat_orchestration_smoke",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "checks=12/12" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_durable_workspace_chat_orchestration_smoke",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert smoke.main([]) == 1
