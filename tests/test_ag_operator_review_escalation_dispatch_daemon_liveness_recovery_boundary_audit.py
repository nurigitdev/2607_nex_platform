from __future__ import annotations

from pathlib import Path

import run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit as audit


def test_ag_dispatch_daemon_liveness_recovery_boundary_passes_repo() -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit()
    )
    boundary = evidence["boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0791"
    assert evidence["surface"] == audit.S80_SURFACE
    assert boundary["boundary"] == audit.BOUNDARY
    assert boundary["source_dispatch_table"] == "ag_op_esc_dispatches"
    assert boundary["source_event_table"] == "service_operational_events"
    assert boundary["source_heartbeat_table"] == "service_worker_heartbeats"
    assert boundary["new_table_in_slice_0791"] is False
    assert boundary["recovery_plan_route_in_slice_0791"] is False
    assert boundary["recovery_plan_mutation_in_slice_0791"] is False
    assert boundary["subprocess_mutation_in_slice_0791"] is False
    assert boundary["first_recovery_action_plan_slice"] == "Slice_0792"
    assert boundary["first_protected_recovery_plan_route_slice"] == "Slice_0793"
    assert boundary["first_recovery_audit_event_slice"] == "Slice_0794"
    assert boundary["first_dashboard_recovery_integration_slice"] == "Slice_0795"
    assert boundary["first_ack_suppression_policy_slice"] == "Slice_0796"
    assert boundary["postgres_smoke_slice"] == "Slice_0797"
    assert boundary["privacy_runbook_slice"] == "Slice_0798"
    assert boundary["contract_openapi_slice"] == "Slice_0799"
    assert boundary["closure_slice"] == "Slice_0800"
    assert evidence["recovery_contract"] == {
        "owner_service": "nex-ag",
        "liveness_source": "service_worker_heartbeats",
        "dispatch_source": "ag_op_esc_dispatches",
        "audit_source": "service_operational_events",
        "existing_liveness_route": (
            "GET /admin/v1/operator-review/dispatch-daemon/liveness"
        ),
        "existing_process_control_route": (
            "POST /admin/v1/operator-review/dispatch-daemon/process-controls"
        ),
        "planned_recovery_plan_route": (
            "GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan"
        ),
        "planned_route_mutation": False,
        "subprocess_mutation_allowed": False,
        "supported_liveness_inputs": [
            "FRESH",
            "MISSING",
            "STALE",
            "SOURCE_NOT_CONFIGURED",
            "SOURCE_UNAVAILABLE",
        ],
        "initial_recovery_actions": {
            "STALE": ["inspect_stale_dispatch_daemon_heartbeat"],
            "MISSING": ["start_or_inspect_dispatch_daemon_process"],
            "SOURCE_NOT_CONFIGURED": ["configure_dispatch_daemon_heartbeat_store"],
            "SOURCE_UNAVAILABLE": ["inspect_dispatch_daemon_heartbeat_store"],
            "FRESH": [],
        },
    }
    assert evidence["separation_of_concerns"] == {
        "liveness_status": "derived_from_service_worker_heartbeats",
        "issue_candidate": "derived_from_liveness_projection_when_daemon_enabled",
        "recovery_plan": "pure_read_model_before_any_control_mutation",
        "process_control": "existing_contract_only_guarded_projection",
        "audit_events": "service_operational_events_safe_summary_only",
        "acknowledgement_suppression": "deferred_to_slice_0796",
    }
    assert evidence["refactoring_checkpoint"] == {
        "reuse_s79_liveness_projection": True,
        "reuse_s78_process_control_projection": True,
        "keep_recovery_plan_pure_and_read_only": True,
        "keep_route_handlers_thin": True,
        "emit_recovery_audit_after_contract_freeze": True,
        "avoid_new_table_until_ack_suppression_policy_is_defined": True,
        "keep_postgres_smoke_real_test_db": True,
        "keep_sensitive_values_redacted": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_names"])
    assert evidence["next_slices"] == [
        "Slice_0792",
        "Slice_0793",
        "Slice_0794",
        "Slice_0795",
        "Slice_0796",
        "Slice_0797",
        "Slice_0798",
        "Slice_0799",
        "Slice_0800",
    ]


def test_ag_dispatch_daemon_liveness_recovery_boundary_summary() -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit()
    )
    summary = audit.summary_line(evidence)

    assert summary.startswith(
        "ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary=pass"
    )
    assert f"boundary={audit.BOUNDARY}" in summary
    assert "new_table=False" in summary
    assert "mutation=False" in summary
    assert "liveness_source=service_worker_heartbeats" in summary
    assert "plan=Slice_0792" in summary
    assert "route=Slice_0793" in summary


def test_ag_dispatch_daemon_liveness_recovery_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_"
        "liveness_recovery_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "liveness_recovery_boundary=fail" in audit.summary_line(evidence)


def test_ag_dispatch_daemon_liveness_recovery_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    for item in audit.REQUIRED_PATHS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["checks"]["s79_closed_baseline_present"] is False
    assert evidence["checks"]["liveness_runtime_present"] is False
    assert evidence["checks"]["process_control_runtime_present"] is False
    assert all(
        item["category"] == "source_token_missing" for item in evidence["issues"]
    )


def test_ag_dispatch_daemon_liveness_recovery_boundary_reports_long_table_name(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "TABLE_NAMES_UNDER_REVIEW",
        (
            "ag_operator_review_escalation_dispatch_daemon_liveness_recovery_too_long",
        ),
    )

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_names_within_limit"] is False
    assert any(item["category"] == "table_name_too_long" for item in evidence["issues"])


def test_ag_dispatch_daemon_liveness_recovery_boundary_group_present_requires_members() -> None:
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


def test_ag_dispatch_daemon_liveness_recovery_boundary_main(
    capsys,
    monkeypatch,
) -> None:
    assert audit.main(["--summary"]) == 0
    assert "liveness_recovery_boundary=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"audit_schema_version"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        (
            "run_ag_operator_review_escalation_dispatch_daemon_"
            "liveness_recovery_boundary_audit"
        ),
        lambda: {
            "status": "FAIL",
            "failure_code": "forced_failure",
            "issues": [{"category": "source_token_missing"}],
        },
    )
    assert audit.main(["--summary"]) == 1
    assert "liveness_recovery_boundary=fail" in capsys.readouterr().out
