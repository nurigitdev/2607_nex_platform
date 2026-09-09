from __future__ import annotations

import json
import shutil
from pathlib import Path

import run_s63_operator_review_evidence_closure as closure


ROOT = Path(__file__).resolve().parents[1]


def test_s63_operator_review_evidence_closure_passes_repo() -> None:
    evidence = closure.run_s63_operator_review_evidence_closure(ROOT)

    assert evidence["status"] == "PASS"
    assert evidence["closure_schema_version"] == closure.SCHEMA_VERSION
    assert evidence["slice_range"] == "0621-0630"
    assert evidence["owned_tables"] == {"ag_op_notes": 11, "ag_ev_exports": 13}
    assert evidence["boundary"] == "ag_owned_operator_review_notes_redacted_exports"
    assert evidence["checks"] == {
        "required_files_present": True,
        "token_checks_present": True,
        "slice_docs_contiguous": True,
        "redaction_scan_safe": True,
        "table_names_short": True,
    }
    assert evidence["experience_matrix"] == {
        "boundary_audit": True,
        "note_schema_store_foundation": True,
        "note_service_idempotency": True,
        "note_protected_routes": True,
        "note_postgresql_smoke": True,
        "export_schema_store_foundation": True,
        "export_service_idempotency": True,
        "export_protected_routes": True,
        "export_postgresql_smoke": True,
        "closure_checkpoint": True,
    }
    assert evidence["redaction_summary"] == {
        "database_url_included": False,
        "shared_password_included": False,
        "provider_api_key_included": False,
        "raw_operator_note_included": False,
        "raw_evidence_body_included": False,
        "idempotency_key_included": False,
        "storage_path_included": False,
        "note_hash_preview_documented": True,
        "export_redacted_manifest_documented": True,
        "protected_postgres_smoke_envs_required": True,
        "ag_owned_boundary_documented": True,
    }
    assert all(item["present"] for item in evidence["required_file_results"])
    assert all(item["present"] for item in evidence["token_results"])

    summary = closure.summary_line(evidence)
    assert summary.startswith("s63_operator_review_evidence_closure=pass")
    assert "slice_range=0621-0630" in summary
    assert "boundary=ag_owned_operator_review_notes_redacted_exports" in summary
    assert "note_table=ag_op_notes" in summary
    assert "export_table=ag_ev_exports" in summary
    assert "smoke=test_db_note_and_export" in summary


def test_s63_operator_review_evidence_closure_reports_missing_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs" / "slices").mkdir(parents=True)

    evidence = closure.run_s63_operator_review_evidence_closure(tmp_path)
    summary = closure.summary_line(evidence)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "closure_checks_failed"
    assert evidence["checks"]["required_files_present"] is False
    assert evidence["checks"]["token_checks_present"] is False
    assert evidence["checks"]["slice_docs_contiguous"] is False
    assert "required_files_present" in summary


def test_s63_operator_review_evidence_closure_reports_token_failure(
    tmp_path: Path,
) -> None:
    _copy_required_files(tmp_path)
    target = tmp_path / "services" / "nex-ag" / "nex_ag" / "operator_reviews.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            'AG_EVIDENCE_EXPORT_TABLE = "ag_ev_exports"',
            'AG_EVIDENCE_EXPORT_TABLE = "ag_evidence_export_records"',
        ),
        encoding="utf-8",
    )

    evidence = closure.run_s63_operator_review_evidence_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_files_present"] is True
    assert evidence["checks"]["slice_docs_contiguous"] is True
    failed = [item for item in evidence["token_results"] if not item["present"]]
    assert failed == [
        {
            "check_id": "export_table_constant",
            "path": "services/nex-ag/nex_ag/operator_reviews.py",
            "present": False,
        }
    ]


def test_s63_operator_review_evidence_closure_reports_redaction_failure(
    tmp_path: Path,
) -> None:
    _copy_required_files(tmp_path)
    target = (
        tmp_path / "docs" / "slices" / "0630_s63_operator_review_evidence_closure.md"
    )
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\npostgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/db\n"
        + "\nag-ev-export-smoke-idem-leaked\n",
        encoding="utf-8",
    )

    evidence = closure.run_s63_operator_review_evidence_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["redaction_scan_safe"] is False
    assert evidence["redaction_summary"]["database_url_included"] is True
    assert evidence["redaction_summary"]["shared_password_included"] is True
    assert evidence["redaction_summary"]["idempotency_key_included"] is True


def test_s63_operator_review_evidence_closure_cli_summary_and_json(
    monkeypatch,
    capsys,
) -> None:
    pass_evidence = {
        "closure_schema_version": closure.SCHEMA_VERSION,
        "status": "PASS",
        "slice_range": "0621-0630",
        "boundary": "ag_owned_operator_review_notes_redacted_exports",
        "required_file_count": len(closure.REQUIRED_FILES),
        "checks": {},
    }
    monkeypatch.setattr(
        closure,
        "run_s63_operator_review_evidence_closure",
        lambda: pass_evidence,
    )

    assert closure.main(["--summary"]) == 0
    assert "s63_operator_review_evidence_closure=pass" in (
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
        "run_s63_operator_review_evidence_closure",
        lambda: fail_evidence,
    )

    assert closure.main([]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "FAIL"


def test_s63_operator_review_evidence_closure_helpers_cover_missing_paths(
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
