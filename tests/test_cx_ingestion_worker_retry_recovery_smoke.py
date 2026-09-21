from __future__ import annotations

import json

import run_cx_ingestion_worker_retry_recovery_smoke as smoke


def test_worker_retry_recovery_smoke_passes() -> None:
    result = smoke.run_cx_ingestion_worker_retry_recovery_smoke()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["checkpoint_version"] == 7
    assert result["postgres_required"] is False
    assert result["dgx_live_provider_required"] is False
    assert result["next_slice"] == "0927"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_cx_ingestion_worker_retry_recovery_smoke()
    assert smoke.summary_line(passing) == (
        "cx_ingestion_worker_retry_recovery=pass checks=10/10 "
        "job=SUCCEEDED run=SUCCEEDED checkpoint=7"
    )
    assert "checks=0/0" in smoke.summary_line({"status": "FAIL"})
    monkeypatch.setattr(
        smoke, "run_cx_ingestion_worker_retry_recovery_smoke", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "retry_recovery=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_cx_ingestion_worker_retry_recovery_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
