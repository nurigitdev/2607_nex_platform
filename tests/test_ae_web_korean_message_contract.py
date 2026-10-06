from __future__ import annotations

import json
from pathlib import Path

import run_ae_web_korean_message_contract as contract


def test_repository_korean_default_message_contract_is_ready() -> None:
    result = contract.run_ae_web_korean_message_contract()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"]["locale_count"] == 2
    assert result["summary"]["required_key_count"] == len(contract.REQUIRED_KEYS)
    assert result["summary"]["parity_key_count"] == len(contract.REQUIRED_KEYS)
    assert result["summary"]["static_binding_count"] >= 35
    assert result["summary"]["accessible_binding_count"] >= 5
    assert result["decision"]["default_locale"] == "ko"
    assert result["decision"]["english_ready"] is True
    assert result["decision"]["next_slice"] == "1384"


def test_message_contract_fails_closed_without_repository(tmp_path: Path) -> None:
    result = contract.run_ae_web_korean_message_contract(tmp_path)

    assert result["status"] == "FAIL"
    assert result["message_contract_readiness"] == "BLOCKED"
    assert result["issues"]
    assert result["decision"]["next_slice"] == "blocked"
    assert set(result["required_key_occurrences"].values()) == {0}


def test_message_contract_helpers_and_cli_paths(monkeypatch, tmp_path, capsys) -> None:
    source = tmp_path / "source.txt"
    source.write_text("한국어", encoding="utf-8")
    assert contract._read_text(source) == "한국어"
    assert contract._read_text(tmp_path / "missing.txt") == ""
    assert contract.summary_line({"status": "FAIL", "issues": [1, 2]}) == (
        "ae_web_korean_message_contract=fail issues=2"
    )

    passing = contract.run_ae_web_korean_message_contract()
    monkeypatch.setattr(
        contract,
        "run_ae_web_korean_message_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "next=1384" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_ae_web_korean_message_contract",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert contract.main([]) == 1
