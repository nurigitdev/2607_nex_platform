from __future__ import annotations

from pathlib import Path

from nex_mo.provider_telemetry_durability_contract import (
    _read_json,
    _read_yaml,
    _table_columns,
    build_mo_provider_telemetry_durability_contract,
)
import run_mo_provider_telemetry_durability_contract as runner


def test_repository_durability_contract_is_aligned() -> None:
    evidence = build_mo_provider_telemetry_durability_contract()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "wire_field_count": 26,
        "openapi_field_count": 26,
        "table_column_count": 24,
        "identity_column_count": 5,
        "counter_column_count": 7,
        "forbidden_column_count": 0,
        "failed_check_count": 0,
    }
    assert evidence["next_slice"] == "1160"


def test_durability_contract_fails_closed_without_repository_sources(
    tmp_path: Path,
) -> None:
    evidence = build_mo_provider_telemetry_durability_contract(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "mo_provider_telemetry_durability_contract_failed"
    )
    assert evidence["summary"]["failed_check_count"] >= 10
    assert evidence["next_slice"] is None


def test_table_column_parser_excludes_constraints_and_missing_tables() -> None:
    sql = """
CREATE TABLE IF NOT EXISTS sample (
    item_id TEXT PRIMARY KEY,
    request_count BIGINT NOT NULL,
    CONSTRAINT ck_sample_count CHECK (request_count >= 0)
);
"""
    assert _table_columns(sql, "sample") == {"item_id", "request_count"}
    assert _table_columns(sql, "missing") == set()


def test_contract_readers_fail_closed_for_invalid_documents(tmp_path: Path) -> None:
    json_path = tmp_path / "bad.json"
    yaml_path = tmp_path / "bad.yaml"
    json_path.write_text("{", encoding="utf-8")
    yaml_path.write_text("value: [", encoding="utf-8")

    assert _read_json(json_path) == {}
    assert _read_yaml(yaml_path) == {}
    assert _read_json(tmp_path / "missing.json") == {}


def test_durability_contract_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_telemetry_durability_contract()
    assert "durability_contract=pass" in runner.summary_line(passing)

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_durability_contract",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "next=1160" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_durability_contract",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
