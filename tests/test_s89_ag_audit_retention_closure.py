from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_s89_ag_audit_retention_closure as closure


def _postgres_pass() -> dict[str, object]:
    return {
        "status": "PASS",
        "observation": {
            "database": "nex_ag_test",
            "backend": "postgresql",
            "purged_receipt_count": 2,
            "indexes_present": {name: True for name in closure.NEW_INDEXES[1:]},
        },
        "lifecycle": {
            "candidate_count": 2,
            "execute_statuses": ["PURGED", "PURGED"],
            "retry_statuses": ["NOOP", "NOOP"],
        },
        "cleanup": {"remaining_rows": 0},
    }


def test_closure_passes_with_default_protected_postgres_skip() -> None:
    result = closure.run_s89_ag_audit_retention_closure(environ={})

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["boundary_audit"]["status"] == "PASS"
    assert result["runtime_evidence"] == {
        "status": "PASS",
        "policy_status": "VALIDATED",
        "candidate_status": "SELECTED",
        "receipt_status": "SEALED",
        "dry_run_status": "ELIGIBLE",
        "execute_status": "PURGED",
        "retry_status": "NOOP",
        "source_deleted": True,
        "raw_values_exposed": False,
    }
    assert result["contract_validation"]["status"] == "PASS"
    assert result["postgres_smoke"]["status"] == "SKIPPED"
    assert result["privacy_runbook"]["status"] == "PASS"
    assert result["source_tables"] == list(closure.SOURCE_TABLES)
    assert result["new_tables"] == ["ag_ret_archives"]
    assert result["new_indexes"] == list(closure.NEW_INDEXES)
    assert result["production_object_storage_implemented"] is False


def test_closure_requires_postgres_pass_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(closure, "run_postgres", lambda _env: _postgres_pass())

    result = closure.run_s89_ag_audit_retention_closure(
        environ={closure.POSTGRES_SMOKE_ENV: "1"}
    )

    assert result["status"] == "PASS"
    assert result["postgres_smoke_opted_in"] is True
    assert result["postgres_smoke"]["status"] == "PASS"


def test_closure_fails_when_opted_in_postgres_does_not_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        closure,
        "run_postgres",
        lambda _env: {"status": "FAIL", "failure_code": "database_failed"},
    )

    result = closure.run_s89_ag_audit_retention_closure(
        environ={closure.POSTGRES_SMOKE_ENV: "1"}
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["postgres_protection_respected"] is False
    assert result["checks"]["postgres_actual_pass_when_opted_in"] is False


def test_runtime_evidence_closes_all_in_memory_surfaces() -> None:
    result = closure._runtime_evidence()

    assert result["policy_status"] == "VALIDATED"
    assert result["candidate_status"] == "SELECTED"
    assert result["receipt_status"] == "SEALED"
    assert result["dry_run_status"] == "ELIGIBLE"
    assert result["execute_status"] == "PURGED"
    assert result["retry_status"] == "NOOP"
    assert result["source_deleted"] is True
    assert result["raw_values_exposed"] is False


def test_safe_evidence_reports_exception_type_without_private_detail() -> None:
    passed = closure._safe_evidence(lambda: {"status": "PASS"}, "unused")
    failed = closure._safe_evidence(
        lambda: (_ for _ in ()).throw(RuntimeError("private failure")),
        "runtime_failed",
    )

    assert passed == {"status": "PASS"}
    assert failed == {
        "status": "FAIL",
        "failure_code": "runtime_failed",
        "error_type": "RuntimeError",
    }
    assert "private failure" not in str(failed)


def test_contract_evidence_handles_validation_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = closure._contract_evidence(closure.ROOT)
    monkeypatch.setattr(
        closure,
        "validate_contract_tree",
        lambda _root: (_ for _ in ()).throw(RuntimeError("private contract")),
    )
    failed = closure._contract_evidence(closure.ROOT)

    assert valid["status"] == "PASS"
    assert valid["schema_count"] >= 81
    assert failed == {
        "status": "FAIL",
        "failure_code": "contract_validation_failed",
        "error_type": "RuntimeError",
    }


def test_required_file_token_and_document_helpers(tmp_path: Path) -> None:
    required = closure._required_file_results(tmp_path)
    tokens = closure._token_results(tmp_path)
    postgres = closure._postgres_doc_evidence(tmp_path)

    assert len(required) == len(closure.REQUIRED_FILES)
    assert len(tokens) == len(closure.TOKEN_CHECKS)
    assert not any(item["present"] for item in required)
    assert not any(item["present"] for item in tokens)
    assert not any(postgres.values())
    assert closure._read_text(tmp_path / "missing") == ""


def test_postgres_document_evidence_is_complete() -> None:
    result = closure._postgres_doc_evidence(closure.ROOT)

    assert all(result.values())
    assert result == {
        "test_database": True,
        "summary_pass": True,
        "two_candidates_purged": True,
        "indexes": True,
        "migration": True,
        "cleanup": True,
    }


def test_summary_line_reports_pass_and_failure() -> None:
    passed = closure.summary_line(
        {
            "status": "PASS",
            "slice_range": closure.SLICE_RANGE,
            "contract_validation": {"status": "PASS"},
            "postgres_smoke": {"status": "SKIPPED"},
            "privacy_runbook": {"status": "PASS"},
        }
    )
    failed = closure.summary_line(
        {
            "status": "FAIL",
            "summary": {"missing_file_count": 1, "missing_token_count": 2},
        }
    )

    assert "closure=pass" in passed
    assert "postgres=SKIPPED" in passed
    assert "closure=fail" in failed
    assert "missing_files=1" in failed
    assert closure._mapping(None) == {}


def test_main_prints_summary_json_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passing = {
        "status": "PASS",
        "slice_range": closure.SLICE_RANGE,
        "contract_validation": {"status": "PASS"},
        "postgres_smoke": {"status": "SKIPPED"},
        "privacy_runbook": {"status": "PASS"},
    }
    monkeypatch.setattr(
        closure,
        "run_s89_ag_audit_retention_closure",
        lambda: passing,
    )

    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s89_ag_audit_retention_closure",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert closure.main([]) == 1
