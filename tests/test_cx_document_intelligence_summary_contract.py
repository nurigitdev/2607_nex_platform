from __future__ import annotations

import json

import run_cx_document_intelligence_summary_contract as contract


def test_document_intelligence_summary_contract_passes() -> None:
    result = contract.run_cx_document_intelligence_summary_contract()

    assert result["status"] == "PASS"
    assert result["passed_checks"] == 10
    assert all(result["checks"].values())
    assert result["summary_hard_limit_chars"] == 1000
    assert result["generation_model"] == "Qwen3.5-4B"
    assert result["embedding_model"] == "Qwen3-Embedding-4B"
    assert result["postgres_required"] is False
    assert result["remote_provider_required"] is False
    assert result["next_slice"] == "0953"


def test_document_intelligence_summary_contract_summary_and_main(
    monkeypatch,
    capsys,
) -> None:
    passing = contract.run_cx_document_intelligence_summary_contract()
    assert contract.summary_line(passing) == (
        "cx_document_intelligence_summary_contract=pass checks=10/10 "
        "hard_limit=1000 postgres_required=False remote_required=False"
    )
    assert "checks=0/0" in contract.summary_line({})

    monkeypatch.setattr(
        contract,
        "run_cx_document_intelligence_summary_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "contract=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_document_intelligence_summary_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
