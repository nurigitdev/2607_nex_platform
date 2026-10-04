from __future__ import annotations

import run_cx_upload_admission_lineage as smoke


def test_restart_lineage_evidence_passes() -> None:
    evidence = smoke.run_cx_upload_admission_lineage()

    assert evidence["status"] == "PASS", evidence
    assert all(evidence["checks"].values())
    assert evidence["durable_counts"] == {
        "source_files": 1,
        "content_objects": 2,
        "ingestion_jobs": 1,
        "ingestion_runs": 1,
    }
    assert evidence["actual_postgres_deferred_to"] == "1350"
    assert evidence["next_slice"] == "1346"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_cx_upload_admission_lineage()
    assert smoke.summary_line(passing) == (
        "cx_upload_admission_lineage=pass checks=10/10 jobs=1 runs=1 next=1346"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "cx_upload_admission_lineage=fail issues=1"
    )

    monkeypatch.setattr(smoke, "run_cx_upload_admission_lineage", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "next=1346" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_cx_upload_admission_lineage",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert smoke.main([]) == 1
