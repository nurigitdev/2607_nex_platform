from __future__ import annotations

import json
import shutil
from pathlib import Path

import run_s52_ae_scheduler_daemon_closure as closure


ROOT = Path(__file__).resolve().parents[1]


def test_s52_ae_scheduler_daemon_closure_passes_for_repo() -> None:
    evidence = closure.run_s52_ae_scheduler_daemon_closure(ROOT)

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "required_files_present": True,
        "token_checks_present": True,
        "slice_docs_contiguous": True,
    }
    assert evidence["experience_matrix"] == {
        "daemon_boundary_audit": True,
        "lease_lock_contract_foundation": True,
        "lease_repository_adapter": True,
        "manual_tick_once_runtime": True,
        "tick_once_postgresql_smoke": True,
        "daemon_config_control_contract": True,
        "daemon_dispatch_facade": True,
        "daemon_service_api_wiring": True,
        "daemon_postgresql_smoke": True,
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
        "storage_path_included": False,
        "storage_ref_included": False,
        "scheduler_daemon_default_disabled": True,
        "continuous_loop_deferred": True,
        "manual_once_runner": True,
        "lease_required_before_tick": True,
        "sqlalchemy_lease_store_backed": True,
        "common_job_backed": True,
        "route_control_ae_owned": True,
        "ag_projection_read_only": True,
        "protected_postgres_smoke_envs_required": True,
        "real_test_db_smoke_evidence_referenced": True,
        "physical_delete_automation_disabled": True,
    }
    assert closure.summary_line(evidence).startswith(
        "s52_ae_scheduler_daemon_closure=pass"
    )


def test_s52_ae_scheduler_daemon_closure_reports_missing_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs" / "slices").mkdir(parents=True)

    evidence = closure.run_s52_ae_scheduler_daemon_closure(tmp_path)
    summary = closure.summary_line(evidence)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "closure_checks_failed"
    assert evidence["checks"]["required_files_present"] is False
    assert evidence["checks"]["token_checks_present"] is False
    assert evidence["checks"]["slice_docs_contiguous"] is False
    assert "required_files_present" in summary


def test_s52_ae_scheduler_daemon_closure_reports_token_failures(
    tmp_path: Path,
) -> None:
    for relative_path in closure.REQUIRED_FILES:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = tmp_path / "services" / "nex-ae-api" / "nex_ae_api" / (
        "artifact_retention_scheduler.py"
    )
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "daemon_disabled_by_policy",
            "daemon_start_disabled",
        ),
        encoding="utf-8",
    )

    evidence = closure.run_s52_ae_scheduler_daemon_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_files_present"] is True
    assert evidence["checks"]["slice_docs_contiguous"] is True
    failed = [item for item in evidence["token_results"] if not item["present"]]
    assert failed == [
        {
            "check_id": "daemon_start_block_reason",
            "path": "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
            "present": False,
        }
    ]


def test_s52_ae_scheduler_daemon_closure_cli_summary_and_json(
    monkeypatch,
    capsys,
) -> None:
    pass_evidence = {
        "closure_schema_version": closure.SCHEMA_VERSION,
        "status": "PASS",
        "slice_range": "0511-0520",
        "required_file_count": len(closure.REQUIRED_FILES),
        "checks": {},
    }
    monkeypatch.setattr(
        closure,
        "run_s52_ae_scheduler_daemon_closure",
        lambda: pass_evidence,
    )

    assert closure.main(["--summary"]) == 0
    assert "s52_ae_scheduler_daemon_closure=pass" in capsys.readouterr().out

    fail_evidence = {
        "closure_schema_version": closure.SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "closure_checks_failed",
        "checks": {"required_files_present": False},
    }
    monkeypatch.setattr(
        closure,
        "run_s52_ae_scheduler_daemon_closure",
        lambda: fail_evidence,
    )

    assert closure.main([]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "FAIL"


def test_s52_ae_scheduler_daemon_closure_read_text_missing(
    tmp_path: Path,
) -> None:
    assert closure._read_text(tmp_path / "missing.md") == ""
