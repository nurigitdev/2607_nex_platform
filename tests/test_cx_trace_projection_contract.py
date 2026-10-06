from __future__ import annotations

import json
from pathlib import Path

from jsonschema import ValidationError

import run_cx_trace_projection_contract as contract


def test_cx_trace_projection_contract_passes() -> None:
    result = contract.run_cx_trace_projection_contract()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "check_count": 10,
        "passed_check_count": 10,
        "stage_count": 3,
        "owner_digest_count": 3,
    }
    assert result["decision"] == {
        "new_table_required": False,
        "database_required": False,
        "remote_provider_required": False,
        "next_slice": "1375",
    }


def test_empty_root_fails_closed(tmp_path: Path) -> None:
    result = contract.run_cx_trace_projection_contract(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failed_checks"]
    assert result["decision"]["next_slice"] == "blocked"


def test_io_and_validation_helpers_fail_closed(tmp_path: Path, monkeypatch) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    assert contract._load_json(tmp_path / "missing.json") is None
    assert contract._load_json(invalid) is None
    assert contract._read_text(tmp_path / "missing.txt") == ""
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
            raise RuntimeError("broken")

    monkeypatch.setattr(contract, "Draft202012Validator", BrokenValidator)
    assert contract._rejects({}, {}) is False


def test_negative_validation_helper(monkeypatch) -> None:
    class RejectingValidator:
        def __init__(self, _schema: object) -> None:
            pass

        def validate(self, _payload: object) -> None:
            raise ValidationError("rejected")

    monkeypatch.setattr(contract, "Draft202012Validator", RejectingValidator)
    assert contract._rejects({}, {}) is True


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = contract.run_cx_trace_projection_contract()
    assert contract.summary_line(passing) == (
        "cx_trace_projection_contract=pass checks=10/10 "
        "stages=3 digests=3 next=1375"
    )
    assert contract.summary_line({}) == (
        "cx_trace_projection_contract=fail checks=0/0 "
        "stages=0 digests=0 next=blocked"
    )

    monkeypatch.setattr(
        contract,
        "run_cx_trace_projection_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "checks=10/10" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_trace_projection_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
