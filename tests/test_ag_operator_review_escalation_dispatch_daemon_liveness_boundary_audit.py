from __future__ import annotations

from pathlib import Path

import run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit as audit


def test_ag_dispatch_daemon_liveness_boundary_passes_repo() -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit()
    )
    boundary = evidence["boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0781"
    assert evidence["surface"] == audit.S79_SURFACE
    assert boundary["boundary"] == audit.BOUNDARY
    assert boundary["source_dispatch_table"] == "ag_op_esc_dispatches"
    assert boundary["source_event_table"] == "service_operational_events"
    assert boundary["source_heartbeat_table"] == "service_worker_heartbeats"
    assert boundary["new_table_in_slice_0781"] is False
    assert boundary["heartbeat_emission_in_slice_0781"] is False
    assert boundary["protected_liveness_route_in_slice_0781"] is False
    assert boundary["dashboard_liveness_mutation_in_slice_0781"] is False
    assert boundary["process_control_mutation_in_s79"] is False
    assert boundary["first_heartbeat_contract_slice"] == "Slice_0782"
    assert boundary["first_heartbeat_emission_slice"] == "Slice_0783"
    assert boundary["first_liveness_read_model_slice"] == "Slice_0784"
    assert boundary["first_protected_liveness_route_slice"] == "Slice_0785"
    assert boundary["first_dashboard_liveness_slice"] == "Slice_0786"
    assert boundary["first_stale_daemon_issue_candidate_slice"] == "Slice_0787"
    assert boundary["postgres_smoke_slice"] == "Slice_0788"
    assert boundary["privacy_runbook_slice"] == "Slice_0789"
    assert boundary["closure_slice"] == "Slice_0790"
    assert evidence["liveness_contract"] == {
        "service_id": "nex-ag",
        "worker_id": "ag-dispatch-execution-daemon",
        "worker_type": "operator_review_dispatch_daemon",
        "source_table": "service_worker_heartbeats",
        "heartbeat_schema_version": "worker_heartbeat.v1",
        "default_stale_after_seconds": 60,
        "max_stale_after_seconds": 86400,
        "statuses": [
            "STARTING",
            "IDLE",
            "BUSY",
            "STOPPING",
            "STOPPED",
            "ERROR",
        ],
        "active_statuses": ["STARTING", "IDLE", "BUSY"],
        "terminal_statuses": ["STOPPED", "ERROR"],
        "new_table_required": False,
        "mutation_in_slice_0781": False,
    }
    assert evidence["separation_of_concerns"] == {
        "lifecycle_source": "service_operational_events",
        "liveness_source": "service_worker_heartbeats",
        "dispatch_source": "ag_op_esc_dispatches",
        "stale_daemon_issue_candidates": "derived_from_heartbeat_read_model",
        "start_stop_controls": "remain_contract_only_no_subprocess_mutation",
    }
    assert evidence["refactoring_checkpoint"] == {
        "reuse_shared_worker_heartbeat_runtime": True,
        "keep_heartbeat_emission_optional_and_explicit": True,
        "keep_lifecycle_events_and_liveness_separate": True,
        "keep_dashboard_stale_state_read_only": True,
        "avoid_new_table_until_heartbeat_query_pressure_is_proven": True,
        "keep_postgres_smoke_real_test_db": True,
        "keep_sensitive_values_redacted": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_names"])
    assert evidence["next_slices"] == [
        "Slice_0782",
        "Slice_0783",
        "Slice_0784",
        "Slice_0785",
        "Slice_0786",
        "Slice_0787",
        "Slice_0788",
        "Slice_0789",
        "Slice_0790",
    ]


def test_ag_dispatch_daemon_liveness_boundary_summary() -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit()
    )
    summary = audit.summary_line(evidence)

    assert summary.startswith(
        "ag_operator_review_escalation_dispatch_daemon_liveness_boundary=pass"
    )
    assert f"boundary={audit.BOUNDARY}" in summary
    assert "new_table=False" in summary
    assert "heartbeat_source=service_worker_heartbeats" in summary
    assert "worker_id=ag-dispatch-execution-daemon" in summary
    assert "contract=Slice_0782" in summary
    assert "read_model=Slice_0784" in summary


def test_ag_dispatch_daemon_liveness_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_liveness_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "liveness_boundary=fail" in audit.summary_line(evidence)


def test_ag_dispatch_daemon_liveness_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    for item in audit.REQUIRED_PATHS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["checks"]["s78_closed_baseline_present"] is False
    assert evidence["checks"]["heartbeat_runtime_present"] is False
    assert evidence["checks"]["process_runtime_present"] is False
    assert all(
        item["category"] == "source_token_missing" for item in evidence["issues"]
    )


def test_ag_dispatch_daemon_liveness_boundary_reports_long_table_name(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "TABLE_NAMES_UNDER_REVIEW",
        ("ag_operator_review_escalation_dispatch_daemon_liveness_rows_too_long",),
    )

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_names_within_limit"] is False
    assert any(item["category"] == "table_name_too_long" for item in evidence["issues"])


def test_ag_dispatch_daemon_liveness_boundary_group_present_requires_members() -> None:
    assert audit._group_present([], "missing_group") is False
    assert (
        audit._group_present(
            [
                {"group": "candidate", "present": True},
                {"group": "candidate", "present": False},
            ],
            "candidate",
        )
        is False
    )
    assert audit._group_present([{"group": "candidate", "present": True}], "candidate")


def test_ag_dispatch_daemon_liveness_boundary_main(capsys, monkeypatch) -> None:
    assert audit.main(["--summary"]) == 0
    assert "liveness_boundary=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"audit_schema_version"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit",
        lambda: {
            "status": "FAIL",
            "failure_code": "forced_failure",
            "issues": [{"category": "source_token_missing"}],
        },
    )
    assert audit.main(["--summary"]) == 1
    assert "liveness_boundary=fail" in capsys.readouterr().out
