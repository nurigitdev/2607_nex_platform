from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_boundary_audit as audit


def test_ag_dispatch_daemon_boundary_passes_repo() -> None:
    evidence = audit.run_ag_operator_review_escalation_dispatch_daemon_boundary_audit()
    boundary = evidence["boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0741"
    assert evidence["surface"] == audit.S75_SURFACE
    assert boundary["boundary"] == audit.BOUNDARY
    assert boundary["source_dispatch_table"] == "ag_op_esc_dispatches"
    assert boundary["create_table_in_slice_0741"] is False
    assert boundary["daemon_loop_in_slice_0741"] is False
    assert boundary["background_process_in_slice_0741"] is False
    assert boundary["real_external_endpoint_delivery"] == (
        "deferred_until_full_system"
    )
    assert boundary["execution_source_of_record"] == "ag_op_esc_dispatches"
    assert boundary["first_policy_slice"] == "Slice_0742"
    assert boundary["first_tick_plan_slice"] == "Slice_0743"
    assert boundary["first_tick_execution_slice"] == "Slice_0744"
    assert boundary["first_postgres_tick_smoke_slice"] == "Slice_0748"
    assert boundary["allowed_execution_modes_now"] == [
        "confirmed_run_once",
        "dry_run",
        "injected_loopback_live_http",
    ]
    assert boundary["job_queue_decision"] == "defer_until_control_api_slice"
    assert boundary["result_storage"] == (
        "ag_op_esc_dispatches.metadata.last_execution_result"
    )
    assert evidence["refactoring_checkpoint"] == {
        "reuse_run_dispatch_execution_worker_once": True,
        "keep_worker_candidate_selection_centralized": True,
        "keep_dispatch_mutations_in_state_machine": True,
        "keep_live_http_transport_injected": True,
        "require_explicit_confirmation": True,
        "support_dry_run_before_execution": True,
        "bound_batch_and_cycle_limits": True,
        "emit_safe_logs_and_events_later": True,
        "avoid_new_table_in_boundary_slice": True,
        "keep_table_names_short": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_name_results"])
    assert evidence["next_slices"] == [
        "Slice_0742",
        "Slice_0743",
        "Slice_0744",
        "Slice_0745",
        "Slice_0746",
        "Slice_0747",
        "Slice_0748",
        "Slice_0749",
        "Slice_0750",
    ]


def test_ag_dispatch_daemon_boundary_summary() -> None:
    evidence = audit.run_ag_operator_review_escalation_dispatch_daemon_boundary_audit()
    summary = audit.summary_line(evidence)

    assert summary.startswith(
        "ag_operator_review_escalation_dispatch_daemon_boundary=pass"
    )
    assert f"boundary={audit.BOUNDARY}" in summary
    assert "daemon_loop=False" in summary
    assert "source=ag_op_esc_dispatches" in summary
    assert "next=Slice_0742" in summary


def test_ag_dispatch_daemon_boundary_reports_missing(tmp_path: Path) -> None:
    evidence = audit.run_ag_operator_review_escalation_dispatch_daemon_boundary_audit(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "daemon_boundary=fail" in audit.summary_line(evidence)


def test_ag_dispatch_daemon_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    root = _minimal_root(tmp_path)
    for item in audit.REQUIRED_PATHS:
        path = root / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = audit.run_ag_operator_review_escalation_dispatch_daemon_boundary_audit(
        root
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["checks"]["worker_runtime_present"] is False
    assert all(item["category"] == "source_token_missing" for item in evidence["issues"])


def test_ag_dispatch_daemon_boundary_table_name_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "TABLE_NAMES_UNDER_REVIEW",
        ("ag_operator_review_escalation_dispatch_execution_daemon_runs",),
    )

    evidence = audit.run_ag_operator_review_escalation_dispatch_daemon_boundary_audit()

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_names_within_limit"] is False
    assert evidence["issues"] == [
        {
            "category": "table_name_too_long",
            "table": "ag_operator_review_escalation_dispatch_execution_daemon_runs",
            "length": 60,
            "limit": audit.MAX_TABLE_NAME_LENGTH,
        }
    ]


def test_ag_dispatch_daemon_boundary_main(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert audit.main(["--summary"]) == 0
    assert "daemon_boundary=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"audit_schema_version"' in capsys.readouterr().out


def _minimal_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root
