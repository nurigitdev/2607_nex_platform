from __future__ import annotations

import json
from pathlib import Path

import run_ag_cross_service_trace_operations_contract as contract


def test_repository_operations_contract_passes() -> None:
    result = contract.run_ag_cross_service_trace_operations_contract()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 12,
        "passed_check_count": 12,
        "source_count": 5,
        "stage_count": 5,
        "audit_event_count": 1,
    }
    assert result["decision"] == {
        "new_table_required": False,
        "database_required": False,
        "remote_provider_required": False,
        "postgres_evidence_slice": "1380",
        "next_slice": "1379",
    }


def test_missing_repository_contract_fails_closed(tmp_path: Path) -> None:
    result = contract.run_ag_cross_service_trace_operations_contract(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["e2e_contract_valid"] is False
    assert result["checks"]["legacy_database_route_removed"] is False
    assert result["decision"]["next_slice"] == "blocked"


def test_helpers_summary_and_cli_paths(monkeypatch, capsys, tmp_path: Path) -> None:
    passing = contract.run_ag_cross_service_trace_operations_contract()
    assert contract.summary_line(passing) == (
        "ag_cross_service_trace_operations_contract=pass checks=12/12 "
        "sources=5 stages=5 audit=1 next=1379"
    )
    assert contract._load_json(tmp_path / "missing") is None
    assert contract._load_yaml(tmp_path / "missing") == {}
    assert contract._read_text(tmp_path / "missing") == ""
    assert contract._validates(None, {}) is False
    invalid = tmp_path / "invalid"
    invalid.write_text("{", encoding="utf-8")
    assert contract._load_json(invalid) is None
    assert contract._load_yaml(invalid) == {}

    monkeypatch.setattr(
        contract,
        "run_ag_cross_service_trace_operations_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "audit=1" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_ag_cross_service_trace_operations_contract",
        lambda: {"status": "FAIL", "summary": {}, "decision": {}},
    )
    assert contract.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
