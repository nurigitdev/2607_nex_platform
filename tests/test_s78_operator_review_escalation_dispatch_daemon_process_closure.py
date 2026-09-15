from __future__ import annotations

from pathlib import Path

import run_s78_operator_review_escalation_dispatch_daemon_process_closure as closure


def test_s78_dispatch_daemon_process_closure_passes_repo() -> None:
    evidence = (
        closure.run_s78_operator_review_escalation_dispatch_daemon_process_closure()
    )

    assert evidence["status"] == "PASS"
    assert evidence["closure_schema_version"] == closure.SCHEMA_VERSION
    assert evidence["slice_range"] == "0771-0780"
    assert evidence["boundary"] == (
        "ag_owned_operator_review_escalation_dispatch_daemon_process"
    )
    assert evidence["source_tables"] == [
        "ag_op_esc_dispatches",
        "service_operational_events",
    ]
    assert evidence["liveness_sources"] == ["service_worker_heartbeats"]
    assert evidence["new_tables"] == []
    assert evidence["process_control_route"] == (
        "POST /admin/v1/operator-review/dispatch-daemon/process-controls"
    )
    assert evidence["postgres_smoke"] == (
        "test_db_lifecycle_events_dashboard_process_control"
    )
    assert evidence["privacy_regression"] == (
        "no_raw_process_secret_token_database_url_or_storage_path"
    )
    assert "dashboard_daemon_process" in evidence["process_surfaces"]
    assert "privacy_runbook_evidence" in evidence["process_surfaces"]
    assert evidence["summary"] == {
        "required_file_count": len(closure.REQUIRED_FILES),
        "missing_file_count": 0,
        "token_check_count": len(closure.TOKEN_CHECKS),
        "missing_token_count": 0,
    }
    assert all(item["present"] for item in evidence["required_files"])
    assert all(item["present"] for item in evidence["token_checks"])


def test_s78_dispatch_daemon_process_closure_summary_line_pass() -> None:
    evidence = (
        closure.run_s78_operator_review_escalation_dispatch_daemon_process_closure()
    )
    summary = closure.summary_line(evidence)

    assert summary.startswith(
        "s78_operator_review_escalation_dispatch_daemon_process_closure=pass"
    )
    assert "slice_range=0771-0780" in summary
    assert "route=POST /admin/v1/operator-review/dispatch-daemon/process-controls" in summary
    assert "smoke=test_db_lifecycle_events_dashboard_process_control" in summary


def test_s78_dispatch_daemon_process_closure_reports_missing_files_and_tokens(
    tmp_path: Path,
) -> None:
    evidence = (
        closure.run_s78_operator_review_escalation_dispatch_daemon_process_closure(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "s78_closure_failed"
    assert evidence["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    summary = closure.summary_line(evidence)
    assert "s78_operator_review_escalation_dispatch_daemon_process_closure=fail" in summary
    assert f"missing_files={len(closure.REQUIRED_FILES)}" in summary


def test_s78_dispatch_daemon_process_closure_token_failure(tmp_path: Path) -> None:
    for path in closure.REQUIRED_FILES:
        file_path = tmp_path / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("placeholder", encoding="utf-8")

    evidence = (
        closure.run_s78_operator_review_escalation_dispatch_daemon_process_closure(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)


def test_s78_dispatch_daemon_process_closure_main_outputs_summary_and_json(
    capsys,
) -> None:
    assert closure.main(["--summary"]) == 0
    assert "dispatch_daemon_process_closure=pass" in capsys.readouterr().out

    assert closure.main([]) == 0
    assert '"closure_schema_version"' in capsys.readouterr().out
