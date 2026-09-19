from __future__ import annotations

from pathlib import Path

import pytest

import run_s87_ag_audit_integrity_evidence_closure as closure


def _postgres_pass() -> dict[str, object]:
    return {
        "status": "PASS",
        "observation": {
            "database": "nex_ag_test",
            "backend": "postgresql",
            "event_count": 3,
            "export_count": 1,
        },
        "package": {"verification_status": "VERIFIED"},
        "cleanup": {"remaining_rows": 0},
    }


def test_closure_passes_with_default_protected_postgres_skip() -> None:
    result = closure.run_s87_ag_audit_integrity_evidence_closure(environ={})

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["boundary_audit"]["status"] == "PASS"
    assert result["runtime_evidence"]["verification_status"] == "VERIFIED"
    assert result["contract_validation"]["status"] == "PASS"
    assert result["postgres_smoke"]["status"] == "SKIPPED"
    assert result["privacy_runbook"]["status"] == "PASS"
    assert result["source_tables"] == [
        "service_operational_events",
        "ag_ev_exports",
    ]
    assert result["new_tables"] == []


def test_closure_requires_postgres_pass_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(closure, "run_postgres", lambda _env: _postgres_pass())

    result = closure.run_s87_ag_audit_integrity_evidence_closure(
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

    result = closure.run_s87_ag_audit_integrity_evidence_closure(
        environ={closure.POSTGRES_SMOKE_ENV: "1"}
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["postgres_protection_respected"] is False
    assert result["checks"]["postgres_actual_pass_when_opted_in"] is False


def test_runtime_evidence_is_verified_deterministic_and_redacted() -> None:
    result = closure._runtime_evidence()

    assert result["status"] == "PASS"
    assert result["integrity_status"] == "VERIFIED"
    assert result["continuity_status"] == "CONTIGUOUS"
    assert result["package_status"] == "VERIFIED"
    assert result["verification_status"] == "VERIFIED"
    assert result["issue_count"] == 0
    assert result["package_id"].startswith("ag-audit-package-")
    assert result["raw_values_exposed"] is False


def test_safe_evidence_reports_exceptions_without_private_detail() -> None:
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
    assert valid["failure_count"] == 0
    assert failed == {
        "status": "FAIL",
        "failure_code": "contract_validation_failed",
        "error_type": "RuntimeError",
    }


def test_file_token_and_postgres_helpers_cover_missing_root(
    tmp_path: Path,
) -> None:
    token_path = tmp_path / closure.TOKEN_CHECKS[0][1]
    token_path.parent.mkdir(parents=True)
    token_path.write_text(closure.TOKEN_CHECKS[0][2], encoding="utf-8")

    files = closure._required_file_results(tmp_path)
    tokens = closure._token_results(tmp_path)
    postgres = closure._postgres_doc_evidence(tmp_path)

    assert not all(item["present"] for item in files)
    assert tokens[0]["present"] is True
    assert tokens[1]["present"] is False
    assert not any(postgres.values())
    assert closure._read_text(tmp_path / "missing") == ""


def test_postgres_documentation_evidence_is_complete() -> None:
    result = closure._postgres_doc_evidence(closure.ROOT)

    assert all(result.values())


def test_summary_line_and_mapping_helpers() -> None:
    passed = closure.summary_line(
        {
            "status": "PASS",
            "slice_range": closure.SLICE_RANGE,
            "contract_validation": {"status": "PASS"},
            "postgres_smoke": {"status": "PASS"},
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
    assert "contracts=PASS" in passed
    assert "postgres=PASS" in passed
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
        "run_s87_ag_audit_integrity_evidence_closure",
        lambda: passing,
    )

    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        closure,
        "run_s87_ag_audit_integrity_evidence_closure",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert closure.main([]) == 1
