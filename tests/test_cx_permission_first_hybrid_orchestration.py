from __future__ import annotations

import json

import pytest

import run_cx_permission_first_hybrid_orchestration as contract


def test_permission_first_hybrid_orchestration_contract_passes() -> None:
    result = contract.run_cx_permission_first_hybrid_orchestration()

    assert result["status"] == "PASS"
    assert result["passed_checks"] == 9
    assert result["failed_checks"] == []
    assert all(result["checks"].values())
    assert result["permission_policy"] == "cx.private_owner_active.v1"
    assert result["tokenizer_used"] in {"mecab_ko", "korean_mixed_v1"}
    assert result["postgres_required"] is False
    assert result["remote_provider_required"] is False


def test_helpers_cover_unexpected_values() -> None:
    fixture = contract._fixture()
    assert fixture["manifest"]["status"] == "READY"
    assert contract._all_keys(1) == []
    bound = contract._BoundVectorStore(fixture["payload_snapshot"], {})
    store = contract._VectorStore("expected", bound)
    with pytest.raises(KeyError):
        store.bind_index({"vector_index_id": "unexpected"})


def test_summary_and_cli_outputs(monkeypatch, capsys) -> None:
    passing = contract.run_cx_permission_first_hybrid_orchestration()
    assert contract.summary_line(passing) == (
        "cx_permission_first_hybrid_orchestration=pass checks=9/9 "
        "postgres_required=False remote_required=False"
    )
    assert "checks=0/0" in contract.summary_line({})

    monkeypatch.setattr(
        contract,
        "run_cx_permission_first_hybrid_orchestration",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "orchestration=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_permission_first_hybrid_orchestration",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
