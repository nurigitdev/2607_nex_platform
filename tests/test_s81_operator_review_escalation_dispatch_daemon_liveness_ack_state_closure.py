from __future__ import annotations

from pathlib import Path

import pytest

import run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure as closure


def test_s81_dispatch_daemon_liveness_ack_state_closure_passes_repo() -> None:
    evidence = (
        closure.run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure()
    )

    assert evidence["status"] == "PASS"
    assert evidence["closure_schema_version"] == closure.SCHEMA_VERSION
    assert evidence["slice_range"] == "0801-0810"
    assert evidence["boundary"] == (
        "ag_owned_operator_review_escalation_dispatch_daemon_liveness_"
        "acknowledgement_suppression_state"
    )
    assert evidence["source_tables"] == ["service_worker_heartbeats"]
    assert evidence["new_tables"] == ["ag_op_review_ack_state"]
    assert evidence["protected_routes"] == [
        closure.ACK_STATE_ACTION_ROUTE,
        closure.ACK_STATE_LIST_ROUTE,
        closure.ACK_STATE_DETAIL_ROUTE,
    ]
    assert "test_db_postgres_smoke_evidence" in evidence["closure_surfaces"]
    assert "privacy_runbook_evidence" in evidence["closure_surfaces"]
    assert evidence["postgres_smoke"]["uses_test_db"] is True
    assert evidence["postgres_smoke"]["summary_pass"] is True
    assert evidence["privacy_runbook"]["status"] == "PASS"
    assert evidence["privacy_runbook"]["runtime_overlay"]["overlay_status"] == (
        "STATE_PRESENT"
    )
    assert evidence["table"] == {
        "name": "ag_op_review_ack_state",
        "length": len("ag_op_review_ack_state"),
        "max_length": closure.MAX_TABLE_NAME_LENGTH,
        "within_limit": True,
    }
    assert evidence["summary"] == {
        "required_file_count": len(closure.REQUIRED_FILES),
        "missing_file_count": 0,
        "token_check_count": len(closure.TOKEN_CHECKS),
        "missing_token_count": 0,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["required_files"])
    assert all(item["present"] for item in evidence["token_checks"])


def test_s81_dispatch_daemon_liveness_ack_state_closure_summary_line_pass() -> None:
    evidence = (
        closure.run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure()
    )
    summary = closure.summary_line(evidence)

    assert summary.startswith(
        "s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure=pass"
    )
    assert "slice_range=0801-0810" in summary
    assert "table=ag_op_review_ack_state" in summary
    assert "routes=3" in summary
    assert "privacy=True" in summary
    assert "postgres_smoke=True" in summary


def test_s81_dispatch_daemon_liveness_ack_state_closure_reports_missing_files_and_tokens(
    tmp_path: Path,
) -> None:
    evidence = (
        closure.run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_"
        "closure_failed"
    )
    assert evidence["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert evidence["postgres_smoke"]["doc_present"] is False
    assert evidence["privacy_runbook"]["status"] == "FAIL"
    summary = closure.summary_line(evidence)
    assert (
        "s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure=fail"
        in summary
    )
    assert f"missing_files={len(closure.REQUIRED_FILES)}" in summary
    assert f"missing_tokens={len(closure.TOKEN_CHECKS)}" in summary


def test_s81_dispatch_daemon_liveness_ack_state_closure_token_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for path in closure.REQUIRED_FILES:
        file_path = tmp_path / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(closure, "run_privacy_runbook", _passing_privacy_result)

    evidence = (
        closure.run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["checks"]["postgres_smoke_used_test_db"] is False


def test_s81_dispatch_daemon_liveness_ack_state_closure_reports_privacy_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        closure,
        "run_privacy_runbook",
        lambda root: {
            "status": "FAIL",
            "failure_code": "privacy_failed",
            "surface_count": 0,
            "checks": {
                "route_static_ready": False,
                "route_runtime_ready": False,
                "route_parameters_ready": False,
                "state_redaction_ready": False,
                "list_redaction_ready": False,
                "redaction_flags_safe": False,
                "forbidden_values_absent": False,
                "forbidden_keys_absent": False,
            },
            "surfaces": {"recovery_overlay": {"overlay_status": "MISSING"}},
        },
    )

    evidence = (
        closure.run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["privacy_runbook_passed"] is False
    assert evidence["checks"]["privacy_route_checks_passed"] is False
    assert evidence["checks"]["privacy_redaction_checks_passed"] is False
    assert evidence["checks"]["runtime_overlay_reads_persisted_state"] is False


def test_s81_dispatch_daemon_liveness_ack_state_closure_reports_privacy_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_privacy_error(root: Path) -> dict[str, object]:
        raise ValueError("broken privacy evidence")

    monkeypatch.setattr(closure, "run_privacy_runbook", raise_privacy_error)

    evidence = (
        closure.run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["privacy_runbook"]["failure_code"] == (
        "privacy_runbook_execution_failed"
    )
    assert "broken privacy evidence" in evidence["privacy_runbook"]["detail"]


def test_s81_dispatch_daemon_liveness_ack_state_closure_helper_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke_doc = tmp_path / closure.POSTGRES_SMOKE_DOC
    smoke_doc.parent.mkdir(parents=True)
    smoke_doc.write_text(
        "nex_ag_test\nliveness_ack_state_postgres_smoke=pass\n<redacted>\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        closure,
        "AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE",
        "ag_operator_review_liveness_acknowledgement_state_too_long",
    )

    assert closure._postgres_smoke_doc_evidence(tmp_path) == {
        "doc": closure.POSTGRES_SMOKE_DOC,
        "doc_present": True,
        "uses_test_db": True,
        "summary_pass": True,
        "redacted_database_url": True,
    }
    table = closure._table_name_evidence()
    assert table["within_limit"] is False
    assert table["length"] > table["max_length"]


def test_s81_dispatch_daemon_liveness_ack_state_closure_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        closure,
        "run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure",
        lambda: {
            "status": "PASS",
            "slice_range": "0801-0810",
            "table": {"name": "ag_op_review_ack_state"},
            "protected_routes": ["a", "b", "c"],
            "checks": {
                "privacy_runbook_passed": True,
                "postgres_smoke_summary_pass": True,
            },
        },
    )

    assert closure.main(["--summary"]) == 0
    assert "liveness_ack_state_closure=pass" in capsys.readouterr().out

    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        closure,
        "run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure",
        lambda: {
            "status": "FAIL",
            "failure_code": "boom",
            "summary": {"missing_file_count": 1, "missing_token_count": 2},
        },
    )
    assert closure.main(["--summary"]) == 1
    assert "liveness_ack_state_closure=fail" in capsys.readouterr().out


def _passing_privacy_result(root: Path) -> dict[str, object]:
    return {
        "status": "PASS",
        "failure_code": None,
        "surface_count": 7,
        "checks": {
            "route_static_ready": True,
            "route_runtime_ready": True,
            "route_parameters_ready": True,
            "state_redaction_ready": True,
            "list_redaction_ready": True,
            "redaction_flags_safe": True,
            "forbidden_values_absent": True,
            "forbidden_keys_absent": True,
        },
        "surfaces": {
            "migration": {"source_table": "ag_op_review_ack_state"},
            "recovery_overlay": {
                "overlay_status": "STATE_PRESENT",
                "source_projection_suppressed": False,
                "issue_candidate_suppressed": False,
            },
        },
    }
