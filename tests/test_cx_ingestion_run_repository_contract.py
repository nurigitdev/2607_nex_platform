from __future__ import annotations

import json

import run_cx_ingestion_run_repository_contract as contract


def test_repository_contract_passes() -> None:
    result = contract.run_cx_ingestion_run_repository_contract()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["table"] == "cx_ingest_runs"
    assert result["table_name_length"] == 14
    assert result["postgres_required"] is False
    assert result["dgx_live_provider_required"] is False
    assert result["next_slice"] == "0924"


def test_summary_line_and_main_paths(monkeypatch, capsys) -> None:
    passing = contract.run_cx_ingestion_run_repository_contract()
    assert contract.summary_line(passing) == (
        "cx_ingestion_run_repository=pass checks=8/8 table=cx_ingest_runs "
        "postgres_required=False dgx_required=False"
    )
    assert "checks=0/0" in contract.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        contract,
        "run_cx_ingestion_run_repository_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "repository=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_ingestion_run_repository_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
