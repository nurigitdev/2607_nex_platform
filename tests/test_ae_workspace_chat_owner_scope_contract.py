from __future__ import annotations

import json

import run_ae_workspace_chat_owner_scope_contract as contract


def test_owner_scope_contract_passes() -> None:
    result = contract.run_owner_scope_contract()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert len(result["checks"]) == 8
    assert result["owner_scope"]["authority"] == "claim"
    assert result["private_fields_included"] is False


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = contract.run_owner_scope_contract()
    assert contract.summary_line(passing) == (
        "ae_workspace_chat_owner_scope=pass checks=8/8 private_fields=False"
    )

    monkeypatch.setattr(contract, "run_owner_scope_contract", lambda: passing)
    assert contract.main(["--summary"]) == 0
    assert "checks=8/8" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_owner_scope_contract",
        lambda: {"status": "FAIL", "checks": {}, "private_fields_included": False},
    )
    assert contract.main([]) == 1
