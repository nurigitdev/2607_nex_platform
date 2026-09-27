from __future__ import annotations

import json
from pathlib import Path

import run_ae_workspace_schema_contract as contract


def test_repository_workspace_schema_contract_passes() -> None:
    result = contract.run_workspace_schema_contract()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["tables"] == ["ae_workspaces", "ae_workspace_activities"]
    assert result["altered_tables"] == ["ae_chat_interactions"]
    assert result["new_table_count"] == 2
    assert result["longest_identifier_length"] <= 63


def test_schema_contract_fails_closed_without_migration(tmp_path: Path) -> None:
    result = contract.run_workspace_schema_contract(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["transactional"] is False
    assert result["checks"]["workspace_table"] is False
    assert result["checks"]["activity_table"] is False
    assert result["checks"]["migration_recorded"] is False
    assert result["identifier_count"] == 0
    assert result["longest_identifier_length"] == 0


def test_identifier_parser_covers_tables_indexes_and_constraints() -> None:
    source = """
    CREATE TABLE IF NOT EXISTS ae_one (
        id TEXT CONSTRAINT ck_ae_one CHECK (id <> '')
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_one ON ae_one (id);
    """

    assert contract._identifiers(source) == {"ae_one", "ck_ae_one", "ux_ae_one"}


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = contract.run_workspace_schema_contract()
    assert "checks=10/10" in contract.summary_line(passing)
    assert "tables=2" in contract.summary_line(passing)

    monkeypatch.setattr(contract, "run_workspace_schema_contract", lambda: passing)
    assert contract.main(["--summary"]) == 0
    assert "ae_workspace_schema=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_workspace_schema_contract",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert contract.main([]) == 1
