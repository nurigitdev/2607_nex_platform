from __future__ import annotations

import json
import shutil
from pathlib import Path

import run_s40_ae_web_repaired_response_review_closure as closure


ROOT = Path(__file__).resolve().parents[1]


def test_s40_ae_web_repaired_response_review_closure_passes_for_repo() -> None:
    evidence = closure.run_s40_ae_web_repaired_response_review_closure(ROOT)

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
        "storage_path_included": False,
    }
    assert closure.summary_line(evidence).startswith(
        "s40_ae_web_repaired_response_review_closure=pass"
    )


def test_s40_ae_web_repaired_response_review_closure_reports_missing_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs" / "slices").mkdir(parents=True)

    evidence = closure.run_s40_ae_web_repaired_response_review_closure(tmp_path)
    summary = closure.summary_line(evidence)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "closure_checks_failed"
    assert evidence["checks"]["required_files_present"] is False
    assert evidence["checks"]["token_checks_present"] is False
    assert evidence["checks"]["slice_docs_contiguous"] is False
    assert "required_files_present" in summary


def test_s40_ae_web_repaired_response_review_closure_reports_token_failures(
    tmp_path: Path,
) -> None:
    for relative_path in closure.REQUIRED_FILES:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = tmp_path / "apps/nex-ae-web" / "src" / "runtimeDiagnostics.js"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "repaired_response_review_count",
            "disabled_response_review_count",
        ),
        encoding="utf-8",
    )

    evidence = closure.run_s40_ae_web_repaired_response_review_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_files_present"] is True
    assert evidence["checks"]["slice_docs_contiguous"] is True
    failed = [item for item in evidence["token_results"] if not item["present"]]
    assert failed == [
        {
            "check_id": "runtime_diagnostics_review_counts",
            "path": "apps/nex-ae-web/src/runtimeDiagnostics.js",
            "present": False,
        }
    ]


def test_s40_ae_web_repaired_response_review_closure_cli_summary_and_json(
    monkeypatch,
    capsys,
) -> None:
    pass_evidence = {
        "closure_schema_version": closure.SCHEMA_VERSION,
        "status": "PASS",
        "slice_range": "0391-0400",
        "required_file_count": len(closure.REQUIRED_FILES),
        "checks": {},
    }
    monkeypatch.setattr(
        closure,
        "run_s40_ae_web_repaired_response_review_closure",
        lambda: pass_evidence,
    )

    assert closure.main(["--summary"]) == 0
    assert "s40_ae_web_repaired_response_review_closure=pass" in (
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
        "run_s40_ae_web_repaired_response_review_closure",
        lambda: fail_evidence,
    )

    assert closure.main([]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "FAIL"


def test_s40_ae_web_repaired_response_review_closure_read_text_missing(
    tmp_path: Path,
) -> None:
    assert closure._read_text(tmp_path / "missing.md") == ""
