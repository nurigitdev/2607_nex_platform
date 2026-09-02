from __future__ import annotations

import json
import shutil
from pathlib import Path

import run_ag_scheduler_daemon_operator_runbook_evidence as runbook


ROOT = Path(__file__).resolve().parents[1]


def test_ag_scheduler_daemon_operator_runbook_evidence_passes_for_repo() -> None:
    evidence = runbook.run_ag_scheduler_daemon_operator_runbook_evidence(ROOT)

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "required_files_present": True,
        "token_checks_present": True,
        "slice_docs_contiguous": True,
        "quality_gate_hooked": True,
        "runbook_redacted": True,
        "runbook_matrix_ready": True,
        "redaction_summary_safe": True,
    }
    assert evidence["operator_runbook_matrix"] == {
        "protected_postgres_smoke_documented": True,
        "manual_tick_guardrail_documented": True,
        "attention_states_documented": True,
        "ae_owns_control_and_persistence": True,
        "ag_read_only_dashboard": True,
    }
    assert evidence["redaction_summary"] == {
        "database_url_included": False,
        "service_token_included": False,
        "provider_api_key_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "metadata_only": True,
        "protected_smoke_envs_required": True,
    }
    assert runbook.summary_line(evidence).startswith(
        "ag_scheduler_daemon_operator_runbook_evidence=pass"
    )


def test_ag_scheduler_daemon_operator_runbook_evidence_reports_missing_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs" / "slices").mkdir(parents=True)

    evidence = runbook.run_ag_scheduler_daemon_operator_runbook_evidence(tmp_path)
    summary = runbook.summary_line(evidence)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "runbook_checks_failed"
    assert evidence["checks"]["required_files_present"] is False
    assert evidence["checks"]["token_checks_present"] is False
    assert evidence["checks"]["slice_docs_contiguous"] is False
    assert evidence["checks"]["runbook_redacted"] is True
    assert "required_files_present" in summary


def test_ag_scheduler_daemon_operator_runbook_evidence_reports_token_failures(
    tmp_path: Path,
) -> None:
    for relative_path in runbook.REQUIRED_FILES:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = tmp_path / runbook.RUNBOOK_PATH
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "BATCH_WINDOW_ATTENTION",
            "BATCH_ATTENTION",
        ),
        encoding="utf-8",
    )

    evidence = runbook.run_ag_scheduler_daemon_operator_runbook_evidence(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_files_present"] is True
    assert evidence["checks"]["slice_docs_contiguous"] is True
    failed = [item for item in evidence["token_results"] if not item["present"]]
    assert failed == [
        {
            "check_id": "runbook_batch_window_attention",
            "path": "docs/runbooks/ag_scheduler_daemon_operations.md",
            "present": False,
        }
    ]


def test_ag_scheduler_daemon_operator_runbook_evidence_redaction_edges(
    tmp_path: Path,
) -> None:
    for relative_path in runbook.REQUIRED_FILES:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = tmp_path / runbook.RUNBOOK_PATH
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\nBearer leaked-token\n"
        + "postgresql+psycopg://user:password@127.0.0.1:5432/db\n",
        encoding="utf-8",
    )

    evidence = runbook.run_ag_scheduler_daemon_operator_runbook_evidence(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["runbook_redacted"] is False
    assert evidence["checks"]["redaction_summary_safe"] is False
    assert evidence["redaction_summary"]["database_url_included"] is True
    assert evidence["redaction_summary"]["service_token_included"] is True


def test_ag_scheduler_daemon_operator_runbook_evidence_cli_summary_and_json(
    monkeypatch,
    capsys,
) -> None:
    pass_evidence = {
        "runbook_evidence_schema_version": runbook.SCHEMA_VERSION,
        "status": "PASS",
        "slice_range": "0521-0530",
        "runbook": runbook.RUNBOOK_PATH,
        "required_file_count": len(runbook.REQUIRED_FILES),
        "checks": {},
    }
    monkeypatch.setattr(
        runbook,
        "run_ag_scheduler_daemon_operator_runbook_evidence",
        lambda: pass_evidence,
    )

    assert runbook.main(["--summary"]) == 0
    assert (
        "ag_scheduler_daemon_operator_runbook_evidence=pass"
        in capsys.readouterr().out
    )

    fail_evidence = {
        "runbook_evidence_schema_version": runbook.SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "runbook_checks_failed",
        "checks": {"required_files_present": False},
    }
    monkeypatch.setattr(
        runbook,
        "run_ag_scheduler_daemon_operator_runbook_evidence",
        lambda: fail_evidence,
    )

    assert runbook.main([]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "FAIL"


def test_ag_scheduler_daemon_operator_runbook_evidence_read_text_missing(
    tmp_path: Path,
) -> None:
    assert runbook._read_text(tmp_path / "missing.md") == ""
