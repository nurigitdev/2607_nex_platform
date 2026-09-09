from __future__ import annotations

import json
import shutil
from pathlib import Path

import run_s62_ae_worker_result_persistence_closure as closure


ROOT = Path(__file__).resolve().parents[1]


def test_s62_ae_worker_result_persistence_closure_passes_repo() -> None:
    evidence = closure.run_s62_ae_worker_result_persistence_closure(ROOT)

    assert evidence["status"] == "PASS"
    assert evidence["closure_schema_version"] == closure.SCHEMA_VERSION
    assert evidence["result_table"] == "ae_op_exec_worker_results"
    assert evidence["result_table_length"] == 25
    assert evidence["new_tables_in_slice_0620"] is False
    assert evidence["checks"] == {
        "required_files_present": True,
        "token_checks_present": True,
        "slice_docs_contiguous": True,
        "redaction_scan_safe": True,
    }
    assert evidence["experience_matrix"] == {
        "worker_result_boundary_audit": True,
        "ae_schema_store_foundation": True,
        "explicit_route_persistence": True,
        "ae_read_model_api": True,
        "ae_postgresql_smoke": True,
        "ag_projection_foundation": True,
        "ag_route_dashboard_wiring": True,
        "ag_postgresql_smoke": True,
        "ag_diagnostics_rollup": True,
        "closure_checkpoint": True,
    }
    assert evidence["redaction_summary"] == {
        "database_url_included": False,
        "service_token_included": False,
        "provider_api_key_included": False,
        "shared_password_included": False,
        "raw_prompt_included": False,
        "raw_generation_output_included": False,
        "raw_source_document_text_included": False,
        "idempotency_key_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_worker_command_included": False,
        "raw_supervisor_result_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "storage_path_included": False,
        "explicit_persist_flag_documented": True,
        "safe_summary_hash_boundary_documented": True,
        "ae_worker_result_postgres_test_db_smoke": True,
        "ag_worker_result_postgres_test_db_smoke": True,
        "ag_read_only_documented": True,
        "diagnostics_metadata_only": True,
        "protected_postgres_smoke_envs_required": True,
        "physical_delete_automation_disabled": True,
    }
    assert all(item["present"] for item in evidence["required_file_results"])
    assert all(item["present"] for item in evidence["token_results"])

    summary = closure.summary_line(evidence)
    assert summary.startswith("s62_ae_worker_result_persistence_closure=pass")
    assert "boundary=ae_owned" in summary
    assert "table=ae_op_exec_worker_results" in summary
    assert "ag_projection=read_only" in summary
    assert "diagnostics=metadata_only" in summary
    assert "smoke=test_db_result_read_model" in summary


def test_s62_ae_worker_result_persistence_closure_reports_missing_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs" / "slices").mkdir(parents=True)

    evidence = closure.run_s62_ae_worker_result_persistence_closure(tmp_path)
    summary = closure.summary_line(evidence)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "closure_checks_failed"
    assert evidence["checks"]["required_files_present"] is False
    assert evidence["checks"]["token_checks_present"] is False
    assert evidence["checks"]["slice_docs_contiguous"] is False
    assert "required_files_present" in summary


def test_s62_ae_worker_result_persistence_closure_reports_token_failure(
    tmp_path: Path,
) -> None:
    _copy_required_files(tmp_path)
    target = (
        tmp_path
        / "services"
        / "nex-ae-api"
        / "nex_ae_api"
        / "artifact_retention_scheduler_daemon.py"
    )
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            'AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE = "ae_op_exec_worker_results"',
            'AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE = "ae_op_exec_worker_rows"',
        ),
        encoding="utf-8",
    )

    evidence = closure.run_s62_ae_worker_result_persistence_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_files_present"] is True
    assert evidence["checks"]["slice_docs_contiguous"] is True
    failed = [item for item in evidence["token_results"] if not item["present"]]
    assert failed == [
        {
            "check_id": "ae_worker_result_table_constant",
            "path": "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
            "present": False,
        }
    ]


def test_s62_ae_worker_result_persistence_closure_reports_redaction_failure(
    tmp_path: Path,
) -> None:
    _copy_required_files(tmp_path)
    target = tmp_path / "docs" / "slices" / (
        "0620_s62_ae_worker_result_persistence_closure.md"
    )
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\npostgresql+psycopg://user:password@127.0.0.1:5432/db\n"
        + "\nraw_worker_command_included\": true\n",
        encoding="utf-8",
    )

    evidence = closure.run_s62_ae_worker_result_persistence_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["redaction_scan_safe"] is False
    assert evidence["redaction_summary"]["database_url_included"] is True
    assert evidence["redaction_summary"]["raw_worker_command_included"] is True


def test_s62_ae_worker_result_persistence_closure_cli_summary_and_json(
    monkeypatch,
    capsys,
) -> None:
    pass_evidence = {
        "closure_schema_version": closure.SCHEMA_VERSION,
        "status": "PASS",
        "slice_range": "0611-0620",
        "result_table": "ae_op_exec_worker_results",
        "required_file_count": len(closure.REQUIRED_FILES),
        "checks": {},
    }
    monkeypatch.setattr(
        closure,
        "run_s62_ae_worker_result_persistence_closure",
        lambda: pass_evidence,
    )

    assert closure.main(["--summary"]) == 0
    assert "s62_ae_worker_result_persistence_closure=pass" in (
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
        "run_s62_ae_worker_result_persistence_closure",
        lambda: fail_evidence,
    )

    assert closure.main([]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "FAIL"


def test_s62_ae_worker_result_persistence_closure_helpers_cover_missing_paths(
    tmp_path: Path,
) -> None:
    assert closure._read_text(tmp_path / "missing.md") == ""
    assert closure._slice_docs_contiguous(tmp_path) is False


def _copy_required_files(tmp_path: Path) -> None:
    for relative_path in closure.REQUIRED_FILES:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
