from __future__ import annotations

from pathlib import Path

from nex_mo.runtime_observability_contract import (
    FORBIDDEN_PUBLIC_FIELDS,
    _mapping,
    _read_json,
    _read_text,
    _read_yaml,
    build_runtime_observability_contract_audit,
)
import run_mo_runtime_observability_contract as runner


def test_repository_runtime_observability_contract_is_hardened() -> None:
    result = build_runtime_observability_contract_audit()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 9,
        "passed_check_count": 9,
        "forbidden_field_count": 7,
        "positive_error_count": 0,
        "negative_error_count": 1,
    }
    assert result["next_slice"] == "1170"


def test_contract_audit_fails_closed_for_missing_tree(tmp_path: Path) -> None:
    result = build_runtime_observability_contract_audit(tmp_path)
    assert result["status"] == "FAIL"
    assert result["next_slice"] is None
    assert result["checks"]["canonical_schema_present"] is False
    assert result["checks"]["positive_fixture_valid"] is False
    assert result["checks"]["openapi_operation_authenticated"] is False


def test_contract_helpers_fail_closed(tmp_path: Path) -> None:
    invalid_json = tmp_path / "invalid.json"
    invalid_yaml = tmp_path / "invalid.yaml"
    invalid_json.write_text("{", encoding="utf-8")
    invalid_yaml.write_text("paths: [", encoding="utf-8")
    assert _read_json(invalid_json) == {}
    assert _read_json(tmp_path / "missing.json") == {}
    assert _read_yaml(invalid_yaml) == {}
    assert _read_yaml(tmp_path / "missing.yaml") == {}
    assert _read_text(tmp_path / "missing.txt") == ""
    assert _mapping(None) == {}
    assert len(FORBIDDEN_PUBLIC_FIELDS) == 7


def test_contract_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_observability_contract()
    assert "runtime_observability_contract=pass" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner, "run_mo_runtime_observability_contract", lambda: passing
    )
    assert runner.main(["--summary"]) == 0
    assert "checks=9/9" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_runtime_observability_contract",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
