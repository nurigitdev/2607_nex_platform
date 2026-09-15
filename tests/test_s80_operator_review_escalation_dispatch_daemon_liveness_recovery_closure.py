from __future__ import annotations

from pathlib import Path

import run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure as closure


def test_s80_dispatch_daemon_liveness_recovery_closure_passes_repo() -> None:
    evidence = (
        closure.run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure()
    )

    assert evidence["status"] == "PASS"
    assert evidence["closure_schema_version"] == closure.SCHEMA_VERSION
    assert evidence["slice_range"] == "0791-0800"
    assert evidence["boundary"] == (
        "ag_owned_operator_review_escalation_dispatch_daemon_liveness_recovery"
    )
    assert evidence["source_tables"] == [
        "service_worker_heartbeats",
        "service_operational_events",
    ]
    assert evidence["new_tables"] == []
    assert evidence["protected_routes"] == [
        "GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan",
        "POST /admin/v1/operator-review/dispatch-daemon/process-controls",
    ]
    assert evidence["postgres_smoke"] == (
        "test_db_service_worker_heartbeats_liveness_recovery_audit_dashboard_issue"
    )
    assert evidence["privacy_regression"] == (
        "no_raw_liveness_secret_token_database_url_storage_path_or_operator_comment"
    )
    assert evidence["acknowledgement_suppression_state"] == {
        "current_state_persisted": False,
        "future_table_candidate": "ag_op_review_ack_state",
        "new_tables_in_s80": [],
    }
    assert "static_openapi_schema_hardening" in evidence["recovery_surfaces"]
    assert "privacy_runbook_and_ack_state_decision_evidence" in (
        evidence["recovery_surfaces"]
    )
    assert evidence["summary"] == {
        "required_file_count": len(closure.REQUIRED_FILES),
        "missing_file_count": 0,
        "token_check_count": len(closure.TOKEN_CHECKS),
        "missing_token_count": 0,
    }
    assert all(item["present"] for item in evidence["required_files"])
    assert all(item["present"] for item in evidence["token_checks"])


def test_s80_dispatch_daemon_liveness_recovery_closure_summary_line_pass() -> None:
    evidence = (
        closure.run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure()
    )
    summary = closure.summary_line(evidence)

    assert summary.startswith(
        "s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure=pass"
    )
    assert "slice_range=0791-0800" in summary
    assert (
        "route=GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan"
        in summary
    )
    assert (
        "smoke=test_db_service_worker_heartbeats_liveness_recovery_audit_dashboard_issue"
        in summary
    )
    assert "ack_state=ag_op_review_ack_state" in summary


def test_s80_dispatch_daemon_liveness_recovery_closure_reports_missing_files_and_tokens(
    tmp_path: Path,
) -> None:
    evidence = (
        closure.run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "s80_closure_failed"
    assert evidence["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    summary = closure.summary_line(evidence)
    assert (
        "s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure=fail"
        in summary
    )
    assert f"missing_files={len(closure.REQUIRED_FILES)}" in summary
    assert f"missing_tokens={len(closure.TOKEN_CHECKS)}" in summary


def test_s80_dispatch_daemon_liveness_recovery_closure_token_failure(
    tmp_path: Path,
) -> None:
    for path in closure.REQUIRED_FILES:
        file_path = tmp_path / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("placeholder", encoding="utf-8")

    evidence = (
        closure.run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)


def test_s80_dispatch_daemon_liveness_recovery_closure_main_outputs_summary_and_json(
    capsys,
) -> None:
    assert closure.main(["--summary"]) == 0
    assert (
        "dispatch_daemon_liveness_recovery_closure=pass"
        in capsys.readouterr().out
    )

    assert closure.main([]) == 0
    assert '"closure_schema_version"' in capsys.readouterr().out
