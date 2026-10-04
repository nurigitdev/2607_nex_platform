from __future__ import annotations

import run_cx_ingestion_restart_cancellation as smoke


def test_restart_cancellation_evidence_passes_without_private_payloads() -> None:
    evidence = smoke.run_cx_ingestion_restart_cancellation()

    assert evidence["status"] == "PASS", evidence
    assert all(evidence["checks"].values())
    assert evidence["private_payload_in_evidence"] is False
    assert evidence["actual_postgres_deferred_to"] == "1350"


def test_restart_cancellation_summary_and_main(monkeypatch, capsys) -> None:
    passing = smoke.run_cx_ingestion_restart_cancellation()
    assert smoke.summary_line(passing) == (
        "cx_ingestion_restart=pass checks=12/12 recovered=1 "
        "work=SUCCEEDED cancel=CANCELLED next=1350"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": ["restart"]}) == (
        "cx_ingestion_restart=fail issues=1"
    )

    monkeypatch.setattr(
        smoke,
        "run_cx_ingestion_restart_cancellation",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "cx_ingestion_restart=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_cx_ingestion_restart_cancellation",
        lambda: {"status": "FAIL", "issues": ["restart"]},
    )
    assert smoke.main(["--summary"]) == 1
