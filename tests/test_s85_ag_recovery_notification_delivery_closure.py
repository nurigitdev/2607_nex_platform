from __future__ import annotations

from pathlib import Path

import pytest

import run_s85_ag_recovery_notification_delivery_closure as closure


def passing_privacy(_root: Path) -> dict[str, object]:
    return {
        "status": "PASS",
        "failure_code": None,
        "surface_count": 9,
        "checks": {
            "forbidden_values_absent": True,
            "forbidden_keys_absent": True,
            "internal_idempotency_signature_preserved": True,
            "runbook_complete": True,
        },
    }


def test_s85_recovery_notification_delivery_closure_passes_repo() -> None:
    evidence = closure.run_s85_ag_recovery_notification_delivery_closure()

    assert evidence["status"] == "PASS"
    assert evidence["closure_schema_version"] == closure.SCHEMA_VERSION
    assert evidence["slice_range"] == "0841-0850"
    assert evidence["boundary"] == (
        "explicit_case_escalation_existing_outbox_mock_delivery"
    )
    assert evidence["source_tables"] == ["ag_op_esc_dispatches"]
    assert evidence["new_tables"] == []
    assert evidence["new_indexes"] == []
    assert evidence["mock_delivery_implemented"] is True
    assert evidence["external_live_delivery_implemented"] is False
    assert len(evidence["closure_surfaces"]) == 9
    assert evidence["runtime"]["admission_status"] == "ADMITTED"
    assert evidence["runtime"]["execution_status"] == "COMPLETED"
    assert evidence["runtime"]["repeat_execution_status"] == "NOOP"
    assert evidence["runtime"]["public_request_signature_exposed"] is False
    assert evidence["postgres_smoke"]["cleanup_verified"] is True
    assert evidence["privacy_runbook"]["status"] == "PASS"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == 0
    assert all(evidence["checks"].values())
    assert "closure=pass" in closure.summary_line(evidence)


def test_s85_recovery_notification_delivery_closure_reports_missing_repo(
    tmp_path: Path,
) -> None:
    evidence = closure.run_s85_ag_recovery_notification_delivery_closure(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == len(
        closure.REQUIRED_FILES
    )
    assert evidence["summary"]["missing_token_count"] == len(
        closure.TOKEN_CHECKS
    )
    assert evidence["postgres_smoke"]["doc_present"] is False
    assert evidence["privacy_runbook"]["status"] == "FAIL"
    assert "closure=fail" in closure.summary_line(evidence)


def test_s85_recovery_notification_delivery_closure_reports_token_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for relative_path in closure.REQUIRED_FILES:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(closure, "run_privacy_runbook", passing_privacy)

    evidence = closure.run_s85_ag_recovery_notification_delivery_closure(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == len(
        closure.TOKEN_CHECKS
    )
    assert evidence["checks"]["required_tokens_present"] is False


def test_s85_recovery_notification_delivery_closure_reports_privacy_failure(
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
                "forbidden_values_absent": False,
                "forbidden_keys_absent": False,
                "internal_idempotency_signature_preserved": False,
                "runbook_complete": False,
            },
        },
    )

    evidence = closure.run_s85_ag_recovery_notification_delivery_closure()

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["privacy_runbook_passed"] is False
    assert evidence["checks"]["privacy_checks_passed"] is False


def test_s85_recovery_notification_delivery_closure_reports_privacy_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        closure,
        "run_privacy_runbook",
        lambda _root: (_ for _ in ()).throw(ValueError("private detail")),
    )

    evidence = closure.run_s85_ag_recovery_notification_delivery_closure()

    assert evidence["status"] == "FAIL"
    assert evidence["privacy_runbook"]["failure_code"] == (
        "privacy_runbook_execution_failed"
    )
    assert evidence["privacy_runbook"]["error_type"] == "ValueError"
    assert "private detail" not in str(evidence["privacy_runbook"])


def test_s85_recovery_notification_delivery_closure_helpers(
    tmp_path: Path,
) -> None:
    smoke_doc = tmp_path / closure.POSTGRES_SMOKE_DOC
    smoke_doc.parent.mkdir(parents=True)
    smoke_doc.write_text(
        "runs current `nex-ag` migrations\n"
        "ag_recovery_notification_delivery_postgres_smoke=pass "
        "database=nex_ag_test backend=postgresql dispatches=1 "
        "succeeded=1 metadata=1 cleaned=True\n"
        "the count of S85 smoke-owned dispatch rows is `0`\n",
        encoding="utf-8",
    )

    postgres = closure._postgres_smoke_doc_evidence(tmp_path)
    runtime = closure._runtime_evidence()

    assert all(value for key, value in postgres.items() if key != "doc")
    assert runtime["admission_status"] == "ADMITTED"
    assert runtime["source_table"] == "ag_op_esc_dispatches"
    assert runtime["created_idempotency_status"] == "NEW"
    assert runtime["replayed_idempotency_status"] == "REPLAYED"
    assert runtime["execution_status"] == "COMPLETED"
    assert runtime["repeat_execution_status"] == "NOOP"
    assert runtime["succeeded_count"] == 1
    assert closure._mapping(None) == {}


def test_s85_recovery_notification_delivery_closure_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        closure,
        "run_s85_ag_recovery_notification_delivery_closure",
        lambda: {
            "status": "PASS",
            "slice_range": closure.SLICE_RANGE,
            "runtime": {"execution_status": "COMPLETED"},
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
        "run_s85_ag_recovery_notification_delivery_closure",
        lambda: {
            "status": "FAIL",
            "summary": {"missing_file_count": 1, "missing_token_count": 2},
        },
    )
    assert closure.main(["--summary"]) == 1
    assert "closure=fail" in capsys.readouterr().out
