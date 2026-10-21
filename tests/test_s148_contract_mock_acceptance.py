from __future__ import annotations

from pathlib import Path

import run_s148_contract_mock_acceptance as smoke
from validate_contracts import contract_inventory_counts

from run_s148_contract_mock_acceptance import main, run_contract_mock_acceptance, summary_line


CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "contracts"


def test_s148_contract_mock_acceptance() -> None:
    result = run_contract_mock_acceptance()
    assert result["status"] == "PASS"
    assert result["contract_counts"] == contract_inventory_counts(CONTRACT_ROOT)
    assert result["external_acceptance"] == "MOCK_ACCEPTED"
    assert result["external_activation"] == "EXTERNAL_NOT_ACTIVATED"
    assert all(result["checks"].values())
    assert summary_line(result).endswith(
        "checks=15/15 acceptance=MOCK_ACCEPTED activation=EXTERNAL_NOT_ACTIVATED next=1482"
    )


def test_s148_contract_mock_acceptance_cli(monkeypatch, capsys) -> None:
    result = run_contract_mock_acceptance()
    monkeypatch.setattr(smoke, "run_contract_mock_acceptance", lambda: result)
    assert main(["--summary"]) == 0
    assert "s148_contract_mock_acceptance=pass" in capsys.readouterr().out
    assert main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_contract_mock_acceptance",
        lambda: {"status": "FAIL", "checks": {}, "next_slice": "blocked"},
    )
    assert main(["--summary"]) == 1
    assert "s148_contract_mock_acceptance=fail" in capsys.readouterr().out
