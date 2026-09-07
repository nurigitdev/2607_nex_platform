from __future__ import annotations

import json
import shutil
from pathlib import Path

import run_s57_ae_scheduler_daemon_supervisor_operations_closure as closure


ROOT = Path(__file__).resolve().parents[1]


def test_s57_ae_scheduler_daemon_supervisor_operations_closure_passes_repo() -> None:
    evidence = closure.run_s57_ae_scheduler_daemon_supervisor_operations_closure(ROOT)

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "required_files_present": True,
        "token_checks_present": True,
        "slice_docs_contiguous": True,
        "redaction_scan_safe": True,
    }
    assert evidence["experience_matrix"] == {
        "supervisor_boundary_audit": True,
        "command_result_contract": True,
        "adapter_foundation": True,
        "persistence_foundation": True,
        "service_api_wiring": True,
        "ae_postgresql_smoke": True,
        "ag_projection_foundation": True,
        "ag_route_wiring": True,
        "ag_postgresql_smoke": True,
        "closure_checkpoint": True,
    }
    assert evidence["redaction_summary"] == {
        "database_url_included": False,
        "service_token_included": False,
        "provider_api_key_included": False,
        "raw_prompt_included": False,
        "raw_generation_output_included": False,
        "raw_source_document_text_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_supervisor_command_included": False,
        "raw_supervisor_result_included": False,
        "storage_path_included": False,
        "storage_ref_included": False,
        "metadata_only_supervisor_boundary": True,
        "fake_dry_run_supervisor_adapter": True,
        "start_daemon_fake_dry_run_blocked": True,
        "stop_daemon_noop_without_process": True,
        "process_start_stop_disabled": True,
        "supervisor_persistence_ae_owned": True,
        "ae_supervisor_read_model_read_only": True,
        "ag_supervisor_projection_read_only": True,
        "protected_postgres_smoke_envs_required": True,
        "real_test_db_smoke_evidence_referenced": True,
        "postgres_short_indexes_hardened": True,
        "smoke_cleanup_verified": True,
        "physical_delete_automation_disabled": True,
    }
    assert all(item["present"] for item in evidence["required_file_results"])
    assert all(item["present"] for item in evidence["token_results"])

    summary = closure.summary_line(evidence)
    assert summary.startswith(
        "s57_ae_scheduler_daemon_supervisor_operations_closure=pass"
    )
    assert "supervisor=ae_owned" in summary
    assert "ag_projection=read_only" in summary
    assert "smoke=test_db_protected" in summary


def test_s57_ae_scheduler_daemon_supervisor_operations_closure_reports_missing_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs" / "slices").mkdir(parents=True)

    evidence = closure.run_s57_ae_scheduler_daemon_supervisor_operations_closure(
        tmp_path
    )
    summary = closure.summary_line(evidence)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "closure_checks_failed"
    assert evidence["checks"]["required_files_present"] is False
    assert evidence["checks"]["token_checks_present"] is False
    assert evidence["checks"]["slice_docs_contiguous"] is False
    assert "required_files_present" in summary


def test_s57_ae_scheduler_daemon_supervisor_operations_closure_reports_token_failure(
    tmp_path: Path,
) -> None:
    for relative_path in closure.REQUIRED_FILES:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = tmp_path / "services" / "nex-ag" / "nex_ag" / "artifact_operations.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_DETAIL_PROJECTION_SCHEMA_VERSION",
            "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_DETAIL_SCHEMA_VERSION",
        ),
        encoding="utf-8",
    )

    evidence = closure.run_s57_ae_scheduler_daemon_supervisor_operations_closure(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_files_present"] is True
    assert evidence["checks"]["slice_docs_contiguous"] is True
    failed = [item for item in evidence["token_results"] if not item["present"]]
    assert failed == [
        {
            "check_id": "ag_supervisor_detail_schema",
            "path": "services/nex-ag/nex_ag/artifact_operations.py",
            "present": False,
        }
    ]


def test_s57_ae_scheduler_daemon_supervisor_operations_closure_reports_redaction_failure(
    tmp_path: Path,
) -> None:
    for relative_path in closure.REQUIRED_FILES:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = tmp_path / "docs" / "slices" / (
        "0570_s57_ae_scheduler_daemon_supervisor_operations_closure.md"
    )
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\npostgresql+psycopg://user:password@127.0.0.1:5432/db\n",
        encoding="utf-8",
    )

    evidence = closure.run_s57_ae_scheduler_daemon_supervisor_operations_closure(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["redaction_scan_safe"] is False


def test_s57_ae_scheduler_daemon_supervisor_operations_closure_cli_summary_and_json(
    monkeypatch,
    capsys,
) -> None:
    pass_evidence = {
        "closure_schema_version": closure.SCHEMA_VERSION,
        "status": "PASS",
        "slice_range": "0561-0570",
        "required_file_count": len(closure.REQUIRED_FILES),
        "checks": {},
    }
    monkeypatch.setattr(
        closure,
        "run_s57_ae_scheduler_daemon_supervisor_operations_closure",
        lambda: pass_evidence,
    )

    assert closure.main(["--summary"]) == 0
    assert "s57_ae_scheduler_daemon_supervisor_operations_closure=pass" in (
        capsys.readouterr().out
    )

    fail_evidence = {
        "closure_schema_version": closure.SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "closure_checks_failed",
        "checks": {"required_files_present": False},
    }
    monkeypatch.setattr(
        closure,
        "run_s57_ae_scheduler_daemon_supervisor_operations_closure",
        lambda: fail_evidence,
    )

    assert closure.main([]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "FAIL"


def test_s57_ae_scheduler_daemon_supervisor_operations_closure_read_text_missing(
    tmp_path: Path,
) -> None:
    assert closure._read_text(tmp_path / "missing.md") == ""
