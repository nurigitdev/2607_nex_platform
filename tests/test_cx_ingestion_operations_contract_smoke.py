from __future__ import annotations

import json

import run_cx_ingestion_operations_contract_smoke as smoke


def test_ingestion_operations_contract_smoke_passes() -> None:
    result = smoke.run_cx_ingestion_operations_contract_smoke()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["restart_action"] == "RECOVER_EXPIRED_LEASE"
    assert result["recovery_status"] == "RETRY_SCHEDULED"
    assert result["checkpoint_version"] == 2
    assert result["postgres_required"] is False
    assert result["next_slice"] == "0929"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_cx_ingestion_operations_contract_smoke()
    assert smoke.summary_line(passing) == (
        "cx_ingestion_operations_contract=pass checks=10/10 "
        "action=RECOVER_EXPIRED_LEASE recovery=RETRY_SCHEDULED"
    )
    assert "checks=0/0" in smoke.summary_line({"status": "FAIL"})
    monkeypatch.setattr(
        smoke,
        "run_cx_ingestion_operations_contract_smoke",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "contract=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_cx_ingestion_operations_contract_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
