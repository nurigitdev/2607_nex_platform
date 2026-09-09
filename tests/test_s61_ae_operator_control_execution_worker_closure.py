from __future__ import annotations

import json
import shutil
from pathlib import Path

import run_s61_ae_operator_control_execution_worker_closure as closure


ROOT = Path(__file__).resolve().parents[1]


def test_s61_ae_operator_control_execution_worker_closure_passes_repo() -> None:
    evidence = closure.run_s61_ae_operator_control_execution_worker_closure(ROOT)

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "required_files_present": True,
        "token_checks_present": True,
        "slice_docs_contiguous": True,
        "redaction_scan_safe": True,
    }
    assert evidence["experience_matrix"] == {
        "worker_boundary_audit": True,
        "plan_command_contract": True,
        "transition_plan_contract": True,
        "fake_dry_run_worker_adapter": True,
        "ae_worker_service_route": True,
        "ae_postgresql_smoke": True,
        "ag_projection_foundation": True,
        "ag_route_wiring": True,
        "ag_to_ae_postgresql_smoke": True,
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
        "metadata_only_worker_boundary": True,
        "worker_result_persistence_deferred": True,
        "ae_worker_postgres_test_db_smoke": True,
        "ag_worker_projection_read_only": True,
        "ag_worker_no_transition_persistence": True,
        "protected_postgres_smoke_envs_required": True,
        "real_test_db_smoke_evidence_referenced": True,
        "scoped_db_write_select_cleanup": True,
        "fake_dry_run_worker_only": True,
        "physical_delete_automation_disabled": True,
    }
    assert all(item["present"] for item in evidence["required_file_results"])
    assert all(item["present"] for item in evidence["token_results"])

    summary = closure.summary_line(evidence)
    assert summary.startswith("s61_ae_operator_control_execution_worker_closure=pass")
    assert "boundary=ae_owned" in summary
    assert "worker=fake_dry_run" in summary
    assert "ag_projection=read_only" in summary
    assert "smoke=test_db_worker_route" in summary


def test_s61_ae_operator_control_execution_worker_closure_reports_missing_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs" / "slices").mkdir(parents=True)

    evidence = closure.run_s61_ae_operator_control_execution_worker_closure(tmp_path)
    summary = closure.summary_line(evidence)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "closure_checks_failed"
    assert evidence["checks"]["required_files_present"] is False
    assert evidence["checks"]["token_checks_present"] is False
    assert evidence["checks"]["slice_docs_contiguous"] is False
    assert "required_files_present" in summary


def test_s61_ae_operator_control_execution_worker_closure_reports_token_failure(
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
            "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PROJECTION_SCHEMA_VERSION",
            "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_SCHEMA_VERSION",
        ),
        encoding="utf-8",
    )

    evidence = closure.run_s61_ae_operator_control_execution_worker_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_files_present"] is True
    assert evidence["checks"]["slice_docs_contiguous"] is True
    failed = [item for item in evidence["token_results"] if not item["present"]]
    assert failed == [
        {
            "check_id": "ag_worker_projection_schema",
            "path": "services/nex-ag/nex_ag/artifact_operations.py",
            "present": False,
        }
    ]


def test_s61_ae_operator_control_execution_worker_closure_reports_redaction_failure(
    tmp_path: Path,
) -> None:
    for relative_path in closure.REQUIRED_FILES:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = tmp_path / "docs" / "slices" / (
        "0610_s61_ae_operator_control_execution_worker_closure.md"
    )
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\npostgresql+psycopg://user:password@127.0.0.1:5432/db\n",
        encoding="utf-8",
    )

    evidence = closure.run_s61_ae_operator_control_execution_worker_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["redaction_scan_safe"] is False
    assert evidence["redaction_summary"]["database_url_included"] is True


def test_s61_ae_operator_control_execution_worker_closure_cli_summary_and_json(
    monkeypatch,
    capsys,
) -> None:
    pass_evidence = {
        "closure_schema_version": closure.SCHEMA_VERSION,
        "status": "PASS",
        "slice_range": "0601-0610",
        "required_file_count": len(closure.REQUIRED_FILES),
        "checks": {},
    }
    monkeypatch.setattr(
        closure,
        "run_s61_ae_operator_control_execution_worker_closure",
        lambda: pass_evidence,
    )

    assert closure.main(["--summary"]) == 0
    assert "s61_ae_operator_control_execution_worker_closure=pass" in (
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
        "run_s61_ae_operator_control_execution_worker_closure",
        lambda: fail_evidence,
    )

    assert closure.main([]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "FAIL"


def test_s61_ae_operator_control_execution_worker_closure_read_text_missing(
    tmp_path: Path,
) -> None:
    assert closure._read_text(tmp_path / "missing.md") == ""


def test_s61_ae_operator_control_execution_worker_closure_slice_docs_missing_dir(
    tmp_path: Path,
) -> None:
    assert closure._slice_docs_contiguous(tmp_path) is False
