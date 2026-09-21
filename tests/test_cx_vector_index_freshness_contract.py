from __future__ import annotations

import json

import run_cx_vector_index_freshness_contract as contract


def test_vector_index_freshness_contract_passes() -> None:
    result = contract.run_cx_vector_index_freshness_contract()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["freshness_state_count"] == 5
    assert result["stale_reason_count"] == 11
    assert result["transition_count"] == 6
    assert result["pipeline_chunk_count"] == 2
    assert result["remote_embedding_required"] is False
    assert result["postgres_required"] is False
    assert result["next_slice"] == "0933"


def test_vector_index_freshness_contract_summary() -> None:
    result = contract.run_cx_vector_index_freshness_contract()

    assert contract.summary_line(result) == (
        "cx_vector_index_freshness_contract=pass checks=8/8 states=5 "
        "reasons=11 transitions=6 remote_required=False"
    )
    assert "checks=0/0" in contract.summary_line({})


def test_vector_index_freshness_contract_main_paths(monkeypatch, capsys) -> None:
    passing = contract.run_cx_vector_index_freshness_contract()
    monkeypatch.setattr(
        contract, "run_cx_vector_index_freshness_contract", lambda: passing
    )
    assert contract.main(["--summary"]) == 0
    assert "contract=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_vector_index_freshness_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
