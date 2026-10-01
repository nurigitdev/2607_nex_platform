from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

import run_mo_operations_integrated_acceptance as runner


def test_deterministic_operations_acceptance_uses_real_components() -> None:
    evidence = runner.run_mo_operations_integrated_acceptance()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "source_count": 4,
        "ready_source_count": 4,
        "capability_count": 3,
        "ready_capability_count": 3,
        "schema_error_count": 0,
        "unauthorized_status": 401,
        "baseline_status": 200,
        "refresh_status": 200,
    }
    assert evidence["next_slice"] == "1189"


def test_acceptance_fails_closed_without_schema(tmp_path: Path) -> None:
    evidence = runner.run_mo_operations_integrated_acceptance(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["canonical_schema_valid"] is False
    assert evidence["summary"]["schema_error_count"] == 1
    assert evidence["next_slice"] == "blocked"


def test_acceptance_fails_closed_for_unwired_app() -> None:
    evidence = runner.run_mo_operations_integrated_acceptance(app=FastAPI())

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["baseline_snapshot_ready"] is False
    assert evidence["summary"]["baseline_status"] == 404


def test_read_json_rejects_invalid_and_non_mapping_payloads(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    sequence = tmp_path / "sequence.json"
    invalid.write_text("{", encoding="utf-8")
    sequence.write_text("[]", encoding="utf-8")

    assert runner._read_json(invalid) == {}
    assert runner._read_json(sequence) == {}
    assert runner._read_json(tmp_path / "missing.json") == {}


def test_integrated_acceptance_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_operations_integrated_acceptance()
    assert runner.summary_line(passing) == (
        "mo_operations_integrated_acceptance=pass sources=4/4 "
        "capabilities=3/3 schema_errors=0 next=1189"
    )
    monkeypatch.setattr(
        runner,
        "run_mo_operations_integrated_acceptance",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "next=1189" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_operations_integrated_acceptance",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
