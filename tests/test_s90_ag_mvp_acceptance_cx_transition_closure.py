from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_s90_ag_mvp_acceptance_cx_transition_closure as closure


def _postgres_pass() -> dict[str, object]:
    return {
        "status": "PASS",
        "database": {"database": "nex_ag_test", "backend": "postgresql"},
        "acceptance": {
            "status": "ACCEPTED",
            "transition_status": "READY_FOR_CX",
            "passed_gate_count": 8,
        },
        "handoff": {
            "candidate_status": "SEALED",
            "attestation_status": "BOUND",
        },
        "cleanup": {"deleted_rows": 1, "remaining_rows": 0},
    }


def test_closure_passes_with_default_protected_postgres_skip() -> None:
    result = closure.run_s90_ag_mvp_acceptance_cx_transition_closure(
        environ={}
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["boundary_audit"]["status"] == "PASS"
    assert result["evidence_inventory"]["status"] == "PASS"
    assert result["contract_validation"]["status"] == "PASS"
    assert result["privacy_runbook"]["status"] == "PASS"
    assert result["postgres_smoke"]["status"] == "SKIPPED"
    assert result["runtime_evidence"]["acceptance_status"] == "ACCEPTED"
    assert result["runtime_evidence"]["attestation_status"] == "BOUND"
    assert result["next_requirement"] == "S91"
    assert result["new_tables"] == []
    assert result["production_release_approved"] is False


def test_closure_requires_postgres_pass_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(closure, "run_postgres", lambda _env: _postgres_pass())

    result = closure.run_s90_ag_mvp_acceptance_cx_transition_closure(
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

    result = closure.run_s90_ag_mvp_acceptance_cx_transition_closure(
        environ={closure.POSTGRES_SMOKE_ENV: "1"}
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["postgres_protection_respected"] is False
    assert result["checks"]["postgres_actual_pass_when_opted_in"] is False


def test_runtime_evidence_closes_acceptance_and_two_stage_handoff() -> None:
    inventory = closure.build_ag_mvp_evidence_inventory()
    contracts = closure._contract_evidence(closure.ROOT)
    privacy = closure.run_privacy()
    postgres_doc = closure._postgres_doc_evidence(closure.ROOT)

    result = closure._runtime_evidence(
        inventory=inventory,
        contracts=contracts,
        privacy=privacy,
        postgres_doc=postgres_doc,
    )

    assert result["status"] == "PASS"
    assert result["acceptance_status"] == "ACCEPTED"
    assert result["transition_status"] == "READY_FOR_CX"
    assert result["passed_gate_count"] == 8
    assert result["candidate_status"] == "SEALED"
    assert result["candidate_verification"] == "VERIFIED"
    assert result["attestation_status"] == "BOUND"
    assert result["attestation_verification"] == "VERIFIED"
    assert result["raw_evidence_exposed"] is False


def test_runtime_evidence_blocks_when_documented_postgres_is_missing() -> None:
    result = closure._runtime_evidence(
        inventory=closure.build_ag_mvp_evidence_inventory(),
        contracts=closure._contract_evidence(closure.ROOT),
        privacy={"status": "PASS"},
        postgres_doc={},
    )

    assert result["status"] == "FAIL"
    assert result["acceptance_status"] == "BLOCKED"
    assert result["attestation_status"] is None
    assert result["attestation_verification"] is None


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
    assert valid["schema_count"] >= 82
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
    assert postgres["passed_tests"] == 0
    assert postgres["statement_percent"] == 0.0
    assert postgres["branch_percent"] == 0.0
    assert closure._read_text(tmp_path / "missing") == ""


def test_postgres_document_evidence_is_complete() -> None:
    result = closure._postgres_doc_evidence(closure.ROOT)

    assert all(
        result[key]
        for key in (
            "live_smoke_passed",
            "test_database",
            "acceptance_accepted",
            "handoff_bound",
            "migration_observed",
            "cleanup_verified",
            "regression_passed",
            "coverage_observed",
        )
    )
    assert result["passed_tests"] == 6256
    assert result["statement_percent"] == pytest.approx(98.84480226581348)
    assert result["branch_percent"] == pytest.approx(96.44497921680157)


def test_number_and_mapping_helpers_cover_present_and_missing_values() -> None:
    assert closure._number("tests=42", r"tests=(\d+)", int) == 42
    assert closure._number("missing", r"tests=(\d+)", int) == 0
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}


def test_summary_line_reports_pass_and_failure() -> None:
    passed = closure.summary_line(
        {
            "status": "PASS",
            "slice_range": closure.SLICE_RANGE,
            "next_requirement": "S91",
            "runtime_evidence": {
                "acceptance_status": "ACCEPTED",
                "attestation_status": "BOUND",
            },
            "postgres_smoke": {"status": "SKIPPED"},
        }
    )
    failed = closure.summary_line(
        {
            "status": "FAIL",
            "summary": {"missing_file_count": 1, "missing_token_count": 2},
        }
    )

    assert "closure=pass" in passed
    assert "acceptance=ACCEPTED" in passed
    assert "handoff=BOUND" in passed
    assert "postgres=SKIPPED" in passed
    assert "next=S91" in passed
    assert "closure=fail" in failed
    assert "missing_files=1" in failed


def test_main_prints_summary_json_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passing = {
        "status": "PASS",
        "slice_range": closure.SLICE_RANGE,
        "next_requirement": "S91",
        "runtime_evidence": {
            "acceptance_status": "ACCEPTED",
            "attestation_status": "BOUND",
        },
        "postgres_smoke": {"status": "SKIPPED"},
    }
    monkeypatch.setattr(
        closure,
        "run_s90_ag_mvp_acceptance_cx_transition_closure",
        lambda: passing,
    )

    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s90_ag_mvp_acceptance_cx_transition_closure",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert closure.main([]) == 1
