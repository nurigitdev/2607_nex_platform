from __future__ import annotations

import json
import shutil
from pathlib import Path

import run_s67_operator_review_case_evidence_admission_closure as closure


ROOT = Path(__file__).resolve().parents[1]


def test_s67_operator_review_case_evidence_admission_closure_passes_repo() -> None:
    evidence = closure.run_s67_operator_review_case_evidence_admission_closure(ROOT)

    assert evidence["status"] == "PASS"
    assert evidence["closure_schema_version"] == closure.SCHEMA_VERSION
    assert evidence["slice_range"] == "0661-0670"
    assert evidence["source_tables"] == {
        "ag_op_cases": 11,
        "ag_op_notes": 11,
        "ag_ev_exports": 13,
    }
    assert evidence["boundary"] == "ag_owned_operator_review_case_evidence_admission"
    assert evidence["action_admission_policy"] == (
        "preflight_only_authoritative_mutation_route"
    )
    assert evidence["checks"] == {
        "required_files_present": True,
        "token_checks_present": True,
        "slice_docs_contiguous": True,
        "redaction_scan_safe": True,
        "table_names_short": True,
        "experience_matrix_closed": True,
    }
    assert evidence["experience_matrix"] == {
        "boundary_audit": True,
        "evidence_link_routes": True,
        "action_admission_routes": True,
        "detail_integration": True,
        "persistence_sources": True,
        "contracts_and_openapi": True,
        "postgres_smoke": True,
        "privacy_regression": True,
        "closure_checkpoint": True,
    }
    assert evidence["redaction_summary"] == {
        "database_url_included": False,
        "shared_password_included": False,
        "provider_api_key_included": False,
        "raw_operator_note_sentinel_included": False,
        "raw_evidence_body_sentinel_included": False,
        "raw_action_comment_sentinel_included": False,
        "raw_resolution_comment_sentinel_included": False,
        "raw_prompt_sentinel_included": False,
        "raw_idempotency_key_included": False,
        "storage_path_included": False,
        "postgres_smoke_documented": True,
        "privacy_regression_documented": True,
        "ag_owned_boundary_documented": True,
        "preflight_policy_documented": True,
    }
    assert all(item["present"] for item in evidence["required_file_results"])
    assert all(item["present"] for item in evidence["token_results"])

    summary = closure.summary_line(evidence)
    assert summary.startswith("s67_operator_review_case_evidence_admission_closure=pass")
    assert "slice_range=0661-0670" in summary
    assert "boundary=ag_owned_operator_review_case_evidence_admission" in summary
    assert "source_tables=ag_op_cases,ag_op_notes,ag_ev_exports" in summary
    assert "privacy=route_surface_regression" in summary


def test_s67_operator_review_case_evidence_admission_closure_reports_missing_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs" / "slices").mkdir(parents=True)

    evidence = closure.run_s67_operator_review_case_evidence_admission_closure(tmp_path)
    summary = closure.summary_line(evidence)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "closure_checks_failed"
    assert evidence["checks"]["required_files_present"] is False
    assert evidence["checks"]["token_checks_present"] is False
    assert evidence["checks"]["slice_docs_contiguous"] is False
    assert "required_files_present" in summary


def test_s67_operator_review_case_evidence_admission_closure_reports_token_failure(
    tmp_path: Path,
) -> None:
    _copy_required_files(tmp_path)
    target = tmp_path / "services" / "nex-ag" / "nex_ag" / "operator_review_cases.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "ag_operator_review_case_action_admission.v1",
            "ag_operator_review_case_action_gate.v1",
            1,
        ),
        encoding="utf-8",
    )

    evidence = closure.run_s67_operator_review_case_evidence_admission_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_files_present"] is True
    assert evidence["checks"]["slice_docs_contiguous"] is True
    assert evidence["checks"]["experience_matrix_closed"] is False
    failed = [item for item in evidence["token_results"] if not item["present"]]
    assert failed == [
        {
            "check_id": "action_admission_schema_version",
            "path": "services/nex-ag/nex_ag/operator_review_cases.py",
            "present": False,
        }
    ]


def test_s67_operator_review_case_evidence_admission_closure_reports_redaction_failure(
    tmp_path: Path,
) -> None:
    _copy_required_files(tmp_path)
    target = (
        tmp_path
        / "docs"
        / "slices"
        / "0670_s67_operator_review_case_evidence_admission_closure.md"
    )
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\npostgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/db\n"
        + "\nRAW_OPERATOR_NOTE_SECRET_0669_SHOULD_NOT_LEAK\n"
        + "\nRAW_EVIDENCE_BODY_SECRET_0669_SHOULD_NOT_LEAK\n"
        + "\nRAW_ACTION_SECRET_0669_SHOULD_NOT_LEAK\n"
        + "\nRAW_RESOLUTION_SECRET_0669_SHOULD_NOT_LEAK\n"
        + "\nRAW_PROMPT_SECRET_0669_SHOULD_NOT_LEAK\n"
        + "\nidem-0669-secret-key\n"
        + "\n/data/nex-platform/private/case-evidence-admission-0669.pdf\n",
        encoding="utf-8",
    )

    evidence = closure.run_s67_operator_review_case_evidence_admission_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["redaction_scan_safe"] is False
    assert evidence["redaction_summary"]["database_url_included"] is True
    assert evidence["redaction_summary"]["shared_password_included"] is True
    assert evidence["redaction_summary"]["raw_operator_note_sentinel_included"] is True
    assert evidence["redaction_summary"]["raw_evidence_body_sentinel_included"] is True
    assert evidence["redaction_summary"]["raw_action_comment_sentinel_included"] is True
    assert evidence["redaction_summary"]["raw_resolution_comment_sentinel_included"] is True
    assert evidence["redaction_summary"]["raw_prompt_sentinel_included"] is True
    assert evidence["redaction_summary"]["raw_idempotency_key_included"] is True
    assert evidence["redaction_summary"]["storage_path_included"] is True


def test_s67_operator_review_case_evidence_admission_closure_cli_summary_and_json(
    monkeypatch,
    capsys,
) -> None:
    pass_evidence = {
        "closure_schema_version": closure.SCHEMA_VERSION,
        "status": "PASS",
        "slice_range": "0661-0670",
        "boundary": "ag_owned_operator_review_case_evidence_admission",
        "required_file_count": len(closure.REQUIRED_FILES),
        "checks": {},
    }
    monkeypatch.setattr(
        closure,
        "run_s67_operator_review_case_evidence_admission_closure",
        lambda: pass_evidence,
    )

    assert closure.main(["--summary"]) == 0
    assert "s67_operator_review_case_evidence_admission_closure=pass" in (
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
        "run_s67_operator_review_case_evidence_admission_closure",
        lambda: fail_evidence,
    )

    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_s67_operator_review_case_evidence_admission_closure_helpers_cover_missing_paths(
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
