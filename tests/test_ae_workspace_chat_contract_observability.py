from __future__ import annotations

import json

import run_ae_workspace_chat_contract_observability as smoke


def test_workspace_chat_contract_observability_smoke_passes() -> None:
    result = smoke.run_workspace_chat_contract_observability_smoke()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["event_count"] == 2
    assert result["postgres_required"] is False
    assert result["remote_provider_required"] is False


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_workspace_chat_contract_observability_smoke()
    summary = smoke.summary_line(passing)
    assert "checks=12/12" in summary
    assert "events=2" in summary

    monkeypatch.setattr(
        smoke,
        "run_workspace_chat_contract_observability_smoke",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "contract_observability=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_workspace_chat_contract_observability_smoke",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert smoke.main([]) == 1
