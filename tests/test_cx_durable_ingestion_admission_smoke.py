from __future__ import annotations

import json

import run_cx_durable_ingestion_admission_smoke as smoke


def test_admission_smoke_passes() -> None:
    result = smoke.run_cx_durable_ingestion_admission_smoke()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["job_count"] == 1
    assert result["run_count"] == 1
    assert result["postgres_required"] is False
    assert result["dgx_live_provider_required"] is False
    assert result["next_slice"] == "0925"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_cx_durable_ingestion_admission_smoke()
    assert smoke.summary_line(passing) == (
        "cx_durable_ingestion_admission=pass checks=8/8 jobs=1 runs=1 "
        "dgx_required=False"
    )
    assert "checks=0/0" in smoke.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        smoke, "run_cx_durable_ingestion_admission_smoke", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "admission=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_cx_durable_ingestion_admission_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
