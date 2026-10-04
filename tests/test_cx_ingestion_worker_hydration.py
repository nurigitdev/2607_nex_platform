from __future__ import annotations

import run_cx_ingestion_worker_hydration as smoke


def test_restart_hydration_evidence_passes() -> None:
    evidence = smoke.run_cx_ingestion_worker_hydration()

    assert evidence["status"] == "PASS", evidence
    assert all(evidence["checks"].values())
    assert evidence["durable_stage_count"] == 3
    assert evidence["private_chunk_reconstruction"] == (
        "markdown_offsets_and_sha256"
    )
    assert evidence["actual_postgres_deferred_to"] == "1350"
    assert evidence["next_slice"] == "1347"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_cx_ingestion_worker_hydration()
    assert "checks=10/10" in smoke.summary_line(passing)
    assert "next=1347" in smoke.summary_line(passing)
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "cx_ingestion_worker_hydration=fail issues=1"
    )

    monkeypatch.setattr(smoke, "run_cx_ingestion_worker_hydration", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "next=1347" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_cx_ingestion_worker_hydration",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert smoke.main([]) == 1
