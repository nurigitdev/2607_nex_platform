from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
import pytest

import run_oa_credential_security_contracts as contracts


ROOT = Path(__file__).resolve().parents[1]


def test_repository_contracts_are_strict_scoped_and_privacy_safe() -> None:
    result = contracts.run_oa_credential_security_contracts()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert all(result["contract_checks"].values())
    assert all(result["privacy_checks"].values())
    assert all(result["operation_checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "schema_count": 2,
        "documented_operation_count": 3,
        "security_implemented_count": 8,
        "security_gap_count": 0,
        "remaining_contract_drift_count": 22,
    }


@pytest.mark.parametrize("name", sorted(contracts.CONTRACTS))
def test_positive_validates_and_negative_privacy_fixture_rejects(name: str) -> None:
    schema_path, positive_path, negative_path = contracts.CONTRACTS[name]
    schema = json.loads((ROOT / schema_path).read_text(encoding="utf-8"))
    positive = json.loads((ROOT / positive_path).read_text(encoding="utf-8"))
    negative = json.loads((ROOT / negative_path).read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(positive)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(negative)


def test_contract_runner_fails_closed_without_inputs(tmp_path: Path) -> None:
    result = contracts.run_oa_credential_security_contracts(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["inputs_present"] is False
    assert result["checks"]["positive_and_negative_contracts"] is False
    assert result["checks"]["operations_protected_and_scoped"] is False
    assert len(result["issues"]) == 7


def test_helpers_cover_invalid_inputs_and_privacy_shapes(tmp_path: Path) -> None:
    issues = []
    invalid_json = tmp_path / "bad.json"
    invalid_json.write_text("{bad", encoding="utf-8")
    invalid_yaml = tmp_path / "bad.yaml"
    invalid_yaml.write_text("paths: [", encoding="utf-8")
    scalar = tmp_path / "scalar.json"
    scalar.write_text("[]", encoding="utf-8")
    scalar_yaml = tmp_path / "scalar.yaml"
    scalar_yaml.write_text("[]", encoding="utf-8")

    assert contracts._load_json(invalid_json, issues, name="bad") == {}
    assert contracts._load_json(scalar, issues, name="scalar") == {}
    assert contracts._load_yaml(invalid_yaml, issues) == {}
    assert contracts._load_yaml(scalar_yaml, issues) == {}
    assert contracts._contains_forbidden_key({"safe": [{"password": "x"}]}) is True
    assert contracts._contains_forbidden_key({"safe": [1, "x"]}) is False
    assert contracts._operation_matches({}, method="get", path="/missing", scopes=[]) is False
    assert contracts._canonical_links({}) is False


def test_summary_and_cli_paths(monkeypatch, capsys) -> None:
    passing = contracts.run_oa_credential_security_contracts()
    assert "contracts=pass" in contracts.summary_line(passing)
    assert "security=8/8" in contracts.summary_line(passing)
    assert "drift=22" in contracts.summary_line(passing)
    monkeypatch.setattr(
        contracts, "run_oa_credential_security_contracts", lambda: passing
    )
    assert contracts.main(["--summary"]) == 0
    assert "operations=3" in capsys.readouterr().out
    assert contracts.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        contracts,
        "run_oa_credential_security_contracts",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert contracts.main([]) == 1
