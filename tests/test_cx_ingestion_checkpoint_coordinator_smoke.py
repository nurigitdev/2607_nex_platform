from __future__ import annotations

import json

import run_cx_ingestion_checkpoint_coordinator_smoke as smoke


def test_checkpoint_smoke_passes() -> None:
    result = smoke.run_cx_ingestion_checkpoint_coordinator_smoke()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["step_count"] == 6
    assert result["checkpoint_version"] == 7
    assert result["postgres_required"] is False
    assert result["dgx_live_provider_required"] is False
    assert result["next_slice"] == "0926"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_cx_ingestion_checkpoint_coordinator_smoke()
    assert smoke.summary_line(passing) == (
        "cx_ingestion_checkpoint_coordinator=pass checks=8/8 steps=6 "
        "checkpoint=7 dgx_required=False"
    )
    assert "checks=0/0" in smoke.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        smoke, "run_cx_ingestion_checkpoint_coordinator_smoke", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "coordinator=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_cx_ingestion_checkpoint_coordinator_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
