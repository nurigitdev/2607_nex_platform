from __future__ import annotations

from pathlib import Path

import run_s77_operator_review_escalation_dispatch_daemon_operations_closure as closure


def test_s77_dispatch_daemon_operations_closure_passes_repo() -> None:
    evidence = (
        closure.run_s77_operator_review_escalation_dispatch_daemon_operations_closure()
    )

    assert evidence["status"] == "PASS"
    assert evidence["closure_schema_version"] == closure.SCHEMA_VERSION
    assert evidence["slice_range"] == "0761-0770"
    assert evidence["boundary"] == (
        "ag_owned_operator_review_escalation_dispatch_daemon_operations"
    )
    assert evidence["source_tables"] == [
        "ag_op_esc_dispatches",
        "service_operational_events",
    ]
    assert evidence["new_tables"] == []
    assert evidence["control_history_route"] == (
        "GET /admin/v1/operator-review/dispatch-daemon/controls"
    )
    assert evidence["postgres_smoke"] == (
        "test_db_control_events_history_dashboard_issue_candidate"
    )
    assert evidence["privacy_regression"] == (
        "no_raw_control_payload_token_database_url_or_storage_path"
    )
    assert "privacy_runbook_evidence" in evidence["operations_surfaces"]
    assert evidence["summary"] == {
        "required_file_count": len(closure.REQUIRED_FILES),
        "missing_file_count": 0,
        "token_check_count": len(closure.TOKEN_CHECKS),
        "missing_token_count": 0,
    }
    assert all(item["present"] for item in evidence["required_files"])
    assert all(item["present"] for item in evidence["token_checks"])


def test_s77_dispatch_daemon_operations_closure_summary_line_pass() -> None:
    evidence = (
        closure.run_s77_operator_review_escalation_dispatch_daemon_operations_closure()
    )
    summary = closure.summary_line(evidence)

    assert summary.startswith(
        "s77_operator_review_escalation_dispatch_daemon_operations_closure=pass"
    )
    assert "slice_range=0761-0770" in summary
    assert "route=GET /admin/v1/operator-review/dispatch-daemon/controls" in summary
    assert "smoke=test_db_control_events_history_dashboard_issue_candidate" in summary


def test_s77_dispatch_daemon_operations_closure_reports_missing_files_and_tokens(
    tmp_path: Path,
) -> None:
    evidence = (
        closure.run_s77_operator_review_escalation_dispatch_daemon_operations_closure(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "s77_closure_failed"
    assert evidence["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    summary = closure.summary_line(evidence)
    assert "s77_operator_review_escalation_dispatch_daemon_operations_closure=fail" in summary
    assert f"missing_files={len(closure.REQUIRED_FILES)}" in summary


def test_s77_dispatch_daemon_operations_closure_token_failure(tmp_path: Path) -> None:
    for path in closure.REQUIRED_FILES:
        file_path = tmp_path / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("placeholder", encoding="utf-8")

    evidence = (
        closure.run_s77_operator_review_escalation_dispatch_daemon_operations_closure(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)


def test_s77_dispatch_daemon_operations_closure_main_outputs_summary_and_json(
    capsys,
) -> None:
    assert closure.main(["--summary"]) == 0
    assert "dispatch_daemon_operations_closure=pass" in capsys.readouterr().out

    assert closure.main([]) == 0
    assert '"closure_schema_version"' in capsys.readouterr().out
