from __future__ import annotations

import json

import run_cx_ingestion_orchestration_contract as contract


def test_contract_evidence_passes() -> None:
    result = contract.run_cx_ingestion_orchestration_contract()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["pipeline_step_count"] == 6
    assert result["transition_count"] == 10
    assert result["dgx_live_provider_required"] is False
    assert result["postgres_required"] is False
    assert result["next_slice"] == "0923"


def test_summary_line_covers_defaults() -> None:
    result = contract.run_cx_ingestion_orchestration_contract()
    assert contract.summary_line(result) == (
        "cx_ingestion_orchestration_contract=pass checks=8/8 steps=6 "
        "transitions=10 dgx_required=False"
    )
    assert contract.summary_line({"status": "FAIL"}) == (
        "cx_ingestion_orchestration_contract=fail checks=0/0 steps=0 "
        "transitions=0 dgx_required=False"
    )


def test_invalid_claim_helper_false_path(monkeypatch) -> None:
    monkeypatch.setattr(contract, "claim_ingestion_run", lambda *args, **kwargs: {})
    assert contract._invalid_claim_rejected({}) is False


def test_main_outputs_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = contract.run_cx_ingestion_orchestration_contract()
    monkeypatch.setattr(
        contract,
        "run_cx_ingestion_orchestration_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "contract=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_ingestion_orchestration_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
