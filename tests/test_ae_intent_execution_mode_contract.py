from __future__ import annotations

import json

import run_ae_intent_execution_mode_contract as contract


def test_contract_evidence_passes() -> None:
    result = contract.run_ae_intent_execution_mode_contract()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["remote_provider_required"] is False
    assert result["next_slice"] == "1024"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = contract.run_ae_intent_execution_mode_contract()
    assert contract.summary_line(passing) == (
        "ae_intent_execution_mode_contract=pass checks=10/10 next=1024"
    )
    assert contract._invalid_mode_code() == "ae.execution_mode_unsupported"

    monkeypatch.setattr(
        contract,
        "run_ae_intent_execution_mode_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "contract=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_ae_intent_execution_mode_contract",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert contract.main([]) == 1
