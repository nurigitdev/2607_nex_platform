from __future__ import annotations

import json
from pathlib import Path

import run_cx_owner_lineage_persistence_contract as contract


def test_owner_lineage_persistence_contract_passes() -> None:
    result = contract.run_cx_owner_lineage_persistence_contract()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"]["lineage_table_count"] == 4
    assert result["summary"]["generation_table_count"] == 1
    assert result["summary"]["issue_count"] == 0
    assert result["decision"]["dgx_live_provider_required"] is False
    assert result["next_slice"] == "0918"


def test_owner_lineage_persistence_contract_fails_closed(tmp_path: Path) -> None:
    result = contract.run_cx_owner_lineage_persistence_contract(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "cx_owner_lineage_persistence_failed"
    assert result["summary"]["issue_count"] > 0
    assert not result["checks"]["required_paths_present"]
    assert contract._read_text(tmp_path / "missing") == ""
    assert contract._table_ddl("", "missing") == ""
    assert contract._table_ddl("CREATE TABLE IF NOT EXISTS sample (id TEXT)", "sample").endswith(
        "(id TEXT)"
    )


def test_contract_summary_and_cli_paths(monkeypatch, capsys) -> None:
    passing = contract.run_cx_owner_lineage_persistence_contract()
    assert contract.summary_line(passing).startswith(
        "cx_owner_lineage_persistence=pass tables=4"
    )
    assert "tables=0" in contract.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        contract,
        "run_cx_owner_lineage_persistence_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "persistence=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_owner_lineage_persistence_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
