from __future__ import annotations

import json
import shutil
from pathlib import Path

import run_s36_remediation_execution_closure as closure


ROOT = Path(__file__).resolve().parents[1]


def test_s36_remediation_execution_closure_passes_for_repo() -> None:
    evidence = closure.run_s36_remediation_execution_closure(ROOT)

    assert evidence["status"] == "PASS"
    assert evidence["checks"] == {
        "required_files_present": True,
        "token_checks_present": True,
        "slice_docs_contiguous": True,
    }
    assert evidence["redaction_summary"] == {
        "database_url_included": False,
        "service_token_included": False,
        "provider_api_key_included": False,
        "raw_prompt_included": False,
        "raw_generation_output_included": False,
        "raw_source_document_text_included": False,
        "raw_evidence_included": False,
    }
    assert closure.summary_line(evidence).startswith(
        "s36_remediation_execution_closure=pass"
    )


def test_s36_remediation_execution_closure_reports_missing_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs" / "slices").mkdir(parents=True)

    evidence = closure.run_s36_remediation_execution_closure(tmp_path)
    summary = closure.summary_line(evidence)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "closure_checks_failed"
    assert evidence["checks"]["required_files_present"] is False
    assert evidence["checks"]["token_checks_present"] is False
    assert evidence["checks"]["slice_docs_contiguous"] is False
    assert "required_files_present" in summary


def test_s36_remediation_execution_closure_reports_token_failures(
    tmp_path: Path,
) -> None:
    for relative_path in closure.REQUIRED_FILES:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = tmp_path / "services/nex-cx/nex_cx/remediation_execution_worker.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "run_cx_remediation_execution_worker_batch",
            "run_cx_remediation_batch_disabled",
        ),
        encoding="utf-8",
    )

    evidence = closure.run_s36_remediation_execution_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    failed = [item for item in evidence["token_results"] if not item["present"]]
    assert failed == [
        {
            "check_id": "cx_worker_runner_batch",
            "path": "services/nex-cx/nex_cx/remediation_execution_worker.py",
            "present": False,
        }
    ]


def test_s36_remediation_execution_closure_cli_summary_and_json(
    monkeypatch,
    capsys,
) -> None:
    pass_evidence = {
        "closure_schema_version": closure.SCHEMA_VERSION,
        "status": "PASS",
        "slice_range": "0351-0360",
        "required_file_count": 33,
        "checks": {},
    }
    monkeypatch.setattr(
        closure,
        "run_s36_remediation_execution_closure",
        lambda: pass_evidence,
    )

    assert closure.main(["--summary"]) == 0
    assert "s36_remediation_execution_closure=pass" in capsys.readouterr().out

    fail_evidence = {
        "closure_schema_version": closure.SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "closure_checks_failed",
        "checks": {"required_files_present": False},
    }
    monkeypatch.setattr(
        closure,
        "run_s36_remediation_execution_closure",
        lambda: fail_evidence,
    )

    assert closure.main([]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "FAIL"
