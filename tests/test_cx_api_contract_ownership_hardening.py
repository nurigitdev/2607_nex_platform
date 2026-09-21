from __future__ import annotations

import json
from pathlib import Path

import run_cx_api_contract_ownership_hardening as hardening


def test_api_contract_ownership_hardening_passes() -> None:
    result = hardening.run_cx_api_contract_ownership_hardening()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "route_module_count": 11,
        "owner_guarded_module_count": 11,
        "runtime_operation_count": 29,
        "drift_count": 0,
        "check_count": 11,
        "issue_count": 0,
    }
    assert result["decision"]["cross_owner_visibility"] == "not-found"
    assert result["decision"]["dgx_live_provider_required"] is False
    assert result["next_slice"] == "0919"


def test_api_contract_ownership_hardening_fails_closed(tmp_path: Path) -> None:
    result = hardening.run_cx_api_contract_ownership_hardening(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "cx_api_ownership_hardening_failed"
    assert result["summary"]["owner_guarded_module_count"] == 0
    assert result["summary"]["issue_count"] > 0
    assert not result["checks"]["required_paths_present"]
    assert hardening._read_text(tmp_path / "missing") == ""


def test_api_contract_ownership_hardening_summary_and_cli(monkeypatch, capsys) -> None:
    passing = hardening.run_cx_api_contract_ownership_hardening()
    assert hardening.summary_line(passing).startswith(
        "cx_api_contract_ownership_hardening=pass modules=11/11"
    )
    assert "modules=0/0" in hardening.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        hardening,
        "run_cx_api_contract_ownership_hardening",
        lambda: passing,
    )
    assert hardening.main(["--summary"]) == 0
    assert "hardening=pass" in capsys.readouterr().out
    assert hardening.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        hardening,
        "run_cx_api_contract_ownership_hardening",
        lambda: {"status": "FAIL"},
    )
    assert hardening.main([]) == 1

