from __future__ import annotations

import json
from pathlib import Path

from jsonschema import ValidationError

import run_platform_trace_envelope_contract as contract


def test_trace_envelope_contract_passes() -> None:
    result = contract.run_platform_trace_envelope_contract()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "check_count": 12,
        "passed_check_count": 12,
        "stage_count": 1,
        "contract_count": 2,
    }
    assert result["decision"] == {
        "private_payload_allowed": False,
        "database_required": False,
        "remote_provider_required": False,
        "next_slice": "1374",
    }


def test_empty_root_fails_closed(tmp_path: Path) -> None:
    result = contract.run_platform_trace_envelope_contract(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failed_checks"]
    assert result["summary"]["passed_check_count"] == 1
    assert result["decision"]["next_slice"] == "blocked"


def test_validation_helpers_fail_closed(monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    assert contract._load_json(missing) is None
    assert contract._load_json(invalid) is None
    assert contract._schema_is_valid(None) is False
    assert contract._schema_is_valid({"type": 1}) is False
    assert contract._validates(None, {}) is False
    assert contract._validates({}, None) is False
    assert contract._validates({"type": "string"}, 1) is False
    assert contract._rejects(None, {}) is False
    assert contract._rejects({}, None) is False
    assert contract._rejects({}, {}) is False

    class BrokenValidator:
        def __init__(self, _schema: object) -> None:
            pass

        def validate(self, _payload: object) -> None:
            raise RuntimeError("validator failure")

    monkeypatch.setattr(contract, "Draft202012Validator", BrokenValidator)
    assert contract._rejects({}, {}) is False


def test_privacy_and_index_helpers_cover_nested_values() -> None:
    assert contract._contains_forbidden_key({"safe": [{"prompt": "x"}]}) is True
    assert contract._contains_forbidden_key({1: {"safe": "x"}}) is False
    assert contract._contains_forbidden_key("safe") is False
    assert contract._paths_registered(None, "examples", set()) is False
    assert contract._paths_registered({}, "examples", set()) is False
    assert contract._paths_registered(
        {"examples": ["bad", {"path": "one.json"}]},
        "examples",
        {"one.json"},
    ) is True


def test_rejects_accepts_validation_error(monkeypatch) -> None:
    class RejectingValidator:
        def __init__(self, _schema: object) -> None:
            pass

        def validate(self, _payload: object) -> None:
            raise ValidationError("rejected")

    monkeypatch.setattr(contract, "Draft202012Validator", RejectingValidator)
    assert contract._rejects({}, {}) is True


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = contract.run_platform_trace_envelope_contract()
    assert contract.summary_line(passing) == (
        "platform_trace_envelope_contract=pass checks=12/12 "
        "stages=1 contracts=2 next=1374"
    )
    assert contract.summary_line({}) == (
        "platform_trace_envelope_contract=fail checks=0/0 "
        "stages=0 contracts=0 next=blocked"
    )

    monkeypatch.setattr(
        contract,
        "run_platform_trace_envelope_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "checks=12/12" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_platform_trace_envelope_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
