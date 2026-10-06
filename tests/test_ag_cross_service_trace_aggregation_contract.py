from __future__ import annotations

import json
from pathlib import Path

import run_ag_cross_service_trace_aggregation_contract as contract


def test_repository_aggregation_contract_passes() -> None:
    result = contract.run_ag_cross_service_trace_aggregation_contract()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 12,
        "passed_check_count": 12,
        "source_count": 4,
        "ready_source_count": 3,
        "stage_count": 3,
        "diagnostic_count": 1,
    }
    assert result["decision"] == {
        "legacy_database_reads_allowed": False,
        "database_required": False,
        "remote_provider_required": False,
        "route_wiring_slice": "1378",
        "next_slice": "1378",
    }


def test_missing_repository_contract_fails_closed(tmp_path: Path) -> None:
    result = contract.run_ag_cross_service_trace_aggregation_contract(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["timeline_contract_valid"] is False
    assert result["checks"]["database_adapter_not_imported"] is True
    assert result["decision"]["next_slice"] == "blocked"


def test_contract_helpers_and_cli_paths(monkeypatch, capsys, tmp_path: Path) -> None:
    passing = contract.run_ag_cross_service_trace_aggregation_contract()
    assert contract.summary_line(passing) == (
        "ag_cross_service_trace_aggregation_contract=pass checks=12/12 "
        "sources=3/4 stages=3 diagnostics=1 next=1378"
    )
    assert contract._load_json(tmp_path / "missing") is None
    assert contract._read_text(tmp_path / "missing") == ""
    assert contract._validates(None, {}) is False
    assert contract._validates({"type": "object"}, []) is False

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    assert contract._load_json(invalid) is None

    monkeypatch.setattr(
        contract,
        "run_ag_cross_service_trace_aggregation_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "sources=3/4" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_ag_cross_service_trace_aggregation_contract",
        lambda: {"status": "FAIL", "summary": {}, "decision": {}},
    )
    assert contract.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
