from __future__ import annotations

from pathlib import Path

import run_s75_operator_review_escalation_dispatch_daemon_closure as closure


def test_s75_dispatch_daemon_closure_passes_repo() -> None:
    evidence = closure.run_s75_operator_review_escalation_dispatch_daemon_closure()

    assert evidence["status"] == "PASS"
    assert evidence["closure_schema_version"] == closure.SCHEMA_VERSION
    assert evidence["slice_range"] == "0741-0750"
    assert evidence["boundary"] == (
        "ag_owned_operator_review_escalation_dispatch_execution_daemon"
    )
    assert evidence["source_table"] == "ag_op_esc_dispatches"
    assert evidence["new_tables"] == []
    assert evidence["daemon_runtime"] == "bounded_confirmed_tick_once_no_background_loop"
    assert evidence["protected_control"] == "control_request_and_admission_foundation"
    assert evidence["live_network_delivery"] == "local_loopback_protected_smoke_only"
    assert evidence["postgres_smoke"] == "test_db_protected_daemon_tick_loopback"
    assert "privacy_regression" in evidence["runtime_surfaces"]
    assert evidence["summary"] == {
        "required_file_count": len(closure.REQUIRED_FILES),
        "missing_file_count": 0,
        "token_check_count": len(closure.TOKEN_CHECKS),
        "missing_token_count": 0,
    }
    assert all(item["present"] for item in evidence["required_files"])
    assert all(item["present"] for item in evidence["token_checks"])


def test_s75_dispatch_daemon_closure_summary_line_pass() -> None:
    evidence = closure.run_s75_operator_review_escalation_dispatch_daemon_closure()
    summary = closure.summary_line(evidence)

    assert summary.startswith(
        "s75_operator_review_escalation_dispatch_daemon_closure=pass"
    )
    assert "slice_range=0741-0750" in summary
    assert "table=ag_op_esc_dispatches" in summary
    assert "runtime=bounded_confirmed_tick_once_no_background_loop" in summary


def test_s75_dispatch_daemon_closure_reports_missing_files_and_tokens(
    tmp_path: Path,
) -> None:
    evidence = closure.run_s75_operator_review_escalation_dispatch_daemon_closure(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "s75_closure_failed"
    assert evidence["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    summary = closure.summary_line(evidence)
    assert "s75_operator_review_escalation_dispatch_daemon_closure=fail" in summary
    assert f"missing_files={len(closure.REQUIRED_FILES)}" in summary


def test_s75_dispatch_daemon_closure_token_failure(tmp_path: Path) -> None:
    for path in closure.REQUIRED_FILES:
        file_path = tmp_path / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("placeholder", encoding="utf-8")

    evidence = closure.run_s75_operator_review_escalation_dispatch_daemon_closure(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)


def test_s75_dispatch_daemon_closure_main_outputs_summary_and_json(capsys) -> None:
    assert closure.main(["--summary"]) == 0
    assert "dispatch_daemon_closure=pass" in capsys.readouterr().out

    assert closure.main([]) == 0
    assert '"closure_schema_version"' in capsys.readouterr().out
