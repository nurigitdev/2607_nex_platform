from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke" / "run_ae_upload_ingestion_progress.py"
SPEC = importlib.util.spec_from_file_location(
    "run_ae_upload_ingestion_progress",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_progress_evidence_is_owner_scoped_ready_and_private() -> None:
    evidence = MODULE.run_ae_upload_ingestion_progress()

    assert evidence["status"] == "PASS", evidence
    assert all(evidence["checks"].values())
    assert evidence["journey_status"] == "INDEX_READY"
    assert evidence["freshness_status"] == "READY"
    assert evidence["private_payload_in_evidence"] is False


def test_progress_evidence_summary_reports_completion() -> None:
    evidence = MODULE.run_ae_upload_ingestion_progress()

    assert MODULE.summary_line(evidence) == (
        "ae_upload_progress=pass checks=12/12 status=INDEX_READY "
        "freshness=READY next=1349"
    )


def test_progress_evidence_failure_summary_is_safe() -> None:
    assert MODULE.summary_line({"status": "FAIL", "issues": ["owner"]}) == (
        "ae_upload_progress=fail issues=1"
    )


def test_main_covers_summary_json_and_failure_exit(monkeypatch, capsys) -> None:
    passing = MODULE.run_ae_upload_ingestion_progress()
    monkeypatch.setattr(MODULE, "run_ae_upload_ingestion_progress", lambda: passing)
    assert MODULE.main(["--summary"]) == 0
    assert "ae_upload_progress=pass" in capsys.readouterr().out
    assert MODULE.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        MODULE,
        "run_ae_upload_ingestion_progress",
        lambda: {"status": "FAIL", "issues": ["owner"]},
    )
    assert MODULE.main(["--summary"]) == 1
