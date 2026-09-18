from __future__ import annotations

from pathlib import Path

import pytest

import run_s83_ag_ack_expiry_automation_closure as closure


def passing_privacy(_root: Path) -> dict[str, object]:
    return {
        "status": "PASS",
        "failure_code": None,
        "surface_count": 8,
        "checks": {
            "forbidden_values_absent": True,
            "forbidden_keys_absent": True,
            "external_scheduler_guardrails": True,
            "runbook_complete": True,
        },
    }


def test_s83_ack_expiry_automation_closure_passes_repo() -> None:
    evidence = closure.run_s83_ag_ack_expiry_automation_closure()

    assert evidence["status"] == "PASS"
    assert evidence["closure_schema_version"] == closure.SCHEMA_VERSION
    assert evidence["slice_range"] == "0821-0830"
    assert evidence["boundary"] == (
        "ag_ack_expiry_externally_scheduled_bounded_run_once"
    )
    assert evidence["source_tables"] == [
        "ag_op_review_ack_state",
        "service_operational_events",
    ]
    assert evidence["new_tables"] == []
    assert evidence["new_indexes"] == []
    assert evidence["scheduler_owner"] == "external_scheduler"
    assert len(evidence["closure_surfaces"]) == 9
    assert evidence["runtime"]["idle_tick"]["candidate_count"] == 0
    assert evidence["runtime"]["idle_tick"]["applied_count"] == 0
    assert evidence["postgres_smoke"]["not_skipped"] is True
    assert evidence["privacy_runbook"]["status"] == "PASS"
    assert evidence["identifiers"]["within_limit"] is True
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == 0
    assert all(evidence["checks"].values())
    assert "closure=pass" in closure.summary_line(evidence)


def test_s83_ack_expiry_automation_closure_reports_missing_repository(
    tmp_path: Path,
) -> None:
    evidence = closure.run_s83_ag_ack_expiry_automation_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert evidence["postgres_smoke"]["doc_present"] is False
    assert evidence["privacy_runbook"]["status"] == "FAIL"
    assert "closure=fail" in closure.summary_line(evidence)


def test_s83_ack_expiry_automation_closure_reports_token_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for relative_path in closure.REQUIRED_FILES:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(closure, "run_privacy_runbook", passing_privacy)

    evidence = closure.run_s83_ag_ack_expiry_automation_closure(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert evidence["checks"]["required_tokens_present"] is False


def test_s83_ack_expiry_automation_closure_reports_privacy_failure(
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
                "external_scheduler_guardrails": False,
                "runbook_complete": False,
            },
        },
    )

    evidence = closure.run_s83_ag_ack_expiry_automation_closure()

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["privacy_runbook_passed"] is False
    assert evidence["checks"]["privacy_checks_passed"] is False


def test_s83_ack_expiry_automation_closure_reports_privacy_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        closure,
        "run_privacy_runbook",
        lambda _root: (_ for _ in ()).throw(ValueError("private detail")),
    )

    evidence = closure.run_s83_ag_ack_expiry_automation_closure()

    assert evidence["status"] == "FAIL"
    assert evidence["privacy_runbook"]["failure_code"] == (
        "privacy_runbook_execution_failed"
    )
    assert evidence["privacy_runbook"]["error_type"] == "ValueError"
    assert "private detail" not in str(evidence["privacy_runbook"])


def test_s83_ack_expiry_automation_closure_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke_doc = tmp_path / closure.POSTGRES_SMOKE_DOC
    smoke_doc.parent.mkdir(parents=True)
    smoke_doc.write_text(
        "nex_ag_test\n"
        "runs all NeX-AG test-profile migrations\n"
        "ag_ack_expiry_automation_postgres_smoke=pass "
        "applied=1 events=2 cleaned=1\n"
        "The result was not skipped\n",
        encoding="utf-8",
    )
    postgres = closure._postgres_smoke_doc_evidence(tmp_path)
    runtime = closure._runtime_evidence()
    monkeypatch.setattr(
        closure,
        "EVENT_TABLE",
        "service_operational_events_identifier_too_long",
    )
    identifiers = closure._identifier_evidence()

    assert all(value for key, value in postgres.items() if key != "doc")
    assert runtime["disabled_policy"]["policy_status"] == "DISABLED"
    assert runtime["healthy_status"] == "HEALTHY"
    assert identifiers["within_limit"] is False
    assert identifiers["lengths"]["event_table"] > identifiers["max_length"]


def test_s83_ack_expiry_automation_closure_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        closure,
        "run_s83_ag_ack_expiry_automation_closure",
        lambda: {
            "status": "PASS",
            "slice_range": closure.SLICE_RANGE,
            "scheduler_owner": "external_scheduler",
            "runtime": {"continuous_loop_started": False},
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
        "run_s83_ag_ack_expiry_automation_closure",
        lambda: {
            "status": "FAIL",
            "summary": {"missing_file_count": 1, "missing_token_count": 2},
        },
    )
    assert closure.main(["--summary"]) == 1
    assert "closure=fail" in capsys.readouterr().out
