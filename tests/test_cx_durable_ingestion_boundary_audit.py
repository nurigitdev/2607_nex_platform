from __future__ import annotations

import json
from pathlib import Path

import run_cx_durable_ingestion_boundary_audit as audit


def test_boundary_audit_freezes_s93_scope() -> None:
    result = audit.run_cx_durable_ingestion_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "GAPS_CONFIRMED"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "volatile_state_count": 2,
        "durable_foundation_count": 3,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert result["decision"]["execution_queue"] == (
        "existing_service_jobs_job_queue"
    )
    assert result["decision"]["orchestration_system_of_record"] == (
        "cx_ingest_runs"
    )
    assert result["decision"]["orchestration_table_name_length"] == 14
    assert result["decision"]["dgx_live_provider_required"] is False
    assert result["next_slice"] == "0922"


def test_boundary_audit_fails_closed_without_inputs(tmp_path: Path) -> None:
    result = audit.run_cx_durable_ingestion_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["checks"]["required_paths_present"] is False
    assert result["checks"]["required_tokens_present"] is False
    assert result["summary"]["issue_count"] == (
        len(audit.REQUIRED_PATHS) + len(audit.EVIDENCE_TOKENS)
    )


def test_helpers_cover_present_and_missing(tmp_path: Path) -> None:
    items = [{"group": "a", "present": True}, {"group": "b", "present": False}]
    assert audit._group_present(items, "a") is True
    assert audit._group_present(items, "b") is False
    assert audit._group_present(items, "missing") is False
    assert audit._read_text(tmp_path / "missing") == ""
    present = tmp_path / "present"
    present.write_text("value", encoding="utf-8")
    assert audit._read_text(present) == "value"


def test_summary_line_covers_defaults() -> None:
    result = audit.run_cx_durable_ingestion_boundary_audit()
    assert audit.summary_line(result) == (
        "cx_durable_ingestion_boundary=pass volatile=2 durable=3 "
        "table=cx_ingest_runs dgx_required=False issues=0"
    )
    assert audit.summary_line({"status": "FAIL"}) == (
        "cx_durable_ingestion_boundary=fail volatile=0 durable=0 "
        "table=unknown dgx_required=False issues=0"
    )


def test_main_covers_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = audit.run_cx_durable_ingestion_boundary_audit()
    monkeypatch.setattr(
        audit,
        "run_cx_durable_ingestion_boundary_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_cx_durable_ingestion_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
