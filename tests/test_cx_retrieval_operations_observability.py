from __future__ import annotations

import json

import run_cx_retrieval_operations_observability as contract


def test_retrieval_operations_observability_contract_passes() -> None:
    result = contract.run_cx_retrieval_operations_observability()

    assert result["status"] == "PASS"
    assert result["passed_checks"] == len(result["checks"]) == 10
    assert result["failed_checks"] == []
    assert result["success_event_type"] == "cx.retrieval.package_observed"
    assert result["failure_event_type"] == "cx.retrieval.package_failed"
    assert result["postgres_required"] is False
    assert result["remote_provider_required"] is False
    serialized = json.dumps(result)
    assert contract.PRIVATE_QUERY not in serialized
    assert contract.PRIVATE_EVIDENCE not in serialized


def test_summary_and_cli_outputs(monkeypatch, capsys) -> None:
    passing = contract.run_cx_retrieval_operations_observability()
    assert contract.summary_line(passing) == (
        "cx_retrieval_operations_observability=pass checks=10/10 "
        "postgres_required=False remote_required=False"
    )
    assert "checks=0/0" in contract.summary_line({})

    monkeypatch.setattr(
        contract,
        "run_cx_retrieval_operations_observability",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "observability=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_retrieval_operations_observability",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
