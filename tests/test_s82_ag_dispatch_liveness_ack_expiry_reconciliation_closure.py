from __future__ import annotations

from pathlib import Path

import pytest

import run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure as closure


def passing_privacy(_root: Path) -> dict[str, object]:
    return {
        "status": "PASS",
        "failure_code": None,
        "surface_count": 10,
        "checks": {
            "cas_conflict_reported": True,
            "idempotent_rerun_empty": True,
            "forbidden_values_absent": True,
            "forbidden_keys_absent": True,
            "runbook_complete": True,
        },
    }


def test_s82_expiry_reconciliation_closure_passes_repo() -> None:
    evidence = closure.run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure()

    assert evidence["status"] == "PASS"
    assert evidence["closure_schema_version"] == closure.SCHEMA_VERSION
    assert evidence["slice_range"] == "0811-0820"
    assert evidence["boundary"] == (
        "ag_owned_dispatch_liveness_ack_expiry_reconciliation"
    )
    assert evidence["source_tables"] == ["ag_op_review_ack_state"]
    assert evidence["new_tables"] == []
    assert evidence["new_indexes"] == ["idx_ag_ack_state_expiry"]
    assert evidence["protected_routes"] == [closure.PROTECTED_ROUTE]
    assert len(evidence["closure_surfaces"]) == 9
    assert evidence["postgres_smoke"]["uses_test_db"] is True
    assert evidence["postgres_smoke"]["cleanup_verified"] is True
    assert evidence["privacy_runbook"]["status"] == "PASS"
    assert evidence["identifiers"]["within_limit"] is True
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == 0
    assert all(evidence["checks"].values())
    assert "closure=pass" in closure.summary_line(evidence)


def test_s82_expiry_reconciliation_closure_reports_missing_repository(
    tmp_path: Path,
) -> None:
    evidence = closure.run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert evidence["postgres_smoke"]["doc_present"] is False
    assert evidence["privacy_runbook"]["status"] == "FAIL"
    assert "closure=fail" in closure.summary_line(evidence)


def test_s82_expiry_reconciliation_closure_reports_token_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for relative_path in closure.REQUIRED_FILES:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(closure, "run_privacy_runbook", passing_privacy)

    evidence = closure.run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert evidence["checks"]["required_tokens_present"] is False


def test_s82_expiry_reconciliation_closure_reports_privacy_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        closure,
        "run_privacy_runbook",
        lambda _root: {
            "status": "FAIL",
            "failure_code": "privacy_failed",
            "surface_count": 0,
            "checks": {
                "cas_conflict_reported": False,
                "idempotent_rerun_empty": False,
                "forbidden_values_absent": False,
                "forbidden_keys_absent": False,
                "runbook_complete": False,
            },
        },
    )

    evidence = closure.run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure()

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["privacy_runbook_passed"] is False
    assert evidence["checks"]["privacy_checks_passed"] is False
    assert evidence["checks"]["conflict_guard_verified"] is False
    assert evidence["checks"]["idempotent_rerun_verified"] is False


def test_s82_expiry_reconciliation_closure_reports_privacy_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        closure,
        "run_privacy_runbook",
        lambda _root: (_ for _ in ()).throw(ValueError("privacy broken")),
    )

    evidence = closure.run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure()

    assert evidence["status"] == "FAIL"
    assert evidence["privacy_runbook"]["failure_code"] == (
        "privacy_runbook_execution_failed"
    )
    assert evidence["privacy_runbook"]["detail"] == "privacy broken"


def test_s82_expiry_reconciliation_closure_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke_doc = tmp_path / closure.POSTGRES_SMOKE_DOC
    smoke_doc.parent.mkdir(parents=True)
    smoke_doc.write_text(
        "nex_ag_test\nReal PostgreSQL result: `PASS`\n"
        "0813_ag_ack_expiry_index\nidx_ag_ack_state_expiry\n"
        "zero candidates\nstale CAS\nzero remaining rows\n",
        encoding="utf-8",
    )
    postgres = closure._postgres_smoke_doc_evidence(tmp_path)
    monkeypatch.setattr(closure, "INDEX_NAME", "idx_ack_expiry_name_too_long_for_policy")
    identifiers = closure._identifier_evidence()

    assert all(
        value
        for key, value in postgres.items()
        if key not in {"doc"}
    )
    assert identifiers["within_limit"] is False
    assert identifiers["lengths"]["index"] > identifiers["max_length"]


def test_s82_expiry_reconciliation_closure_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        closure,
        "run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure",
        lambda: {
            "status": "PASS",
            "slice_range": closure.SLICE_RANGE,
            "checks": {
                "postgres_smoke_passed": True,
                "privacy_runbook_passed": True,
            },
        },
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        closure,
        "run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure",
        lambda: {
            "status": "FAIL",
            "summary": {"missing_file_count": 1, "missing_token_count": 2},
        },
    )
    assert closure.main(["--summary"]) == 1
    assert "closure=fail" in capsys.readouterr().out
